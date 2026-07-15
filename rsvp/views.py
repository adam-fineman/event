from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.http import HttpResponseForbidden
from django.db import transaction
from django.core.serializers.json import DjangoJSONEncoder
import json

from .models import (
    Event, RSVP, RSVPMenuSelection, FamilyMember, FamilyMemberMenuSelection,
    MenuCategory, MenuItem, Invitation, Table,
)
from .forms import RSVPForm, LockedEmailRSVPForm, build_menu_form


INVITATION_AUTH_SESSION_KEY = 'invitation_authenticated'
INVITATION_EMAIL_SESSION_KEY = 'invitation_email'


def _session_invitation_email(request):
    if not request.session.get(INVITATION_AUTH_SESSION_KEY):
        return None
    return request.session.get(INVITATION_EMAIL_SESSION_KEY)


def event_list(request):
    invitation_email = _session_invitation_email(request)
    if not invitation_email:
        return HttpResponseForbidden("Forbidden")

    events = Event.objects.filter(invitations__email__iexact=invitation_email).distinct().order_by('date')
    return render(request, 'rsvp/event_list.html', {'events': events})


def rsvp_form(request, event_pk):
    invitation_email = _session_invitation_email(request)
    if not invitation_email:
        return HttpResponseForbidden("Forbidden")

    event = get_object_or_404(Event, pk=event_pk)
    invitation = Invitation.objects.filter(event=event, email__iexact=invitation_email).first()
    if not invitation:
        return HttpResponseForbidden("Forbidden")

    if not event.is_accepting_rsvps:
        messages.error(request, "The RSVP deadline for this event has passed.")
        return redirect('event_list')

    existing_rsvp = invitation.rsvp or RSVP.objects.filter(event=event, email__iexact=invitation_email).first()

    categories = list(MenuCategory.objects.filter(event=event).prefetch_related('items'))
    has_menu = bool(categories)
    menu_cats_json = _menu_categories_json(categories)

    # Existing family members (read-only)
    existing_family_members = []
    if existing_rsvp:
        existing_family_members = list(existing_rsvp.family_members.all())

    if request.method == 'POST':
        rsvp_form_inst = LockedEmailRSVPForm(
            request.POST,
            instance=existing_rsvp,
            prefix='rsvp',
            initial={
                'first_name': invitation.first_name,
                'last_name': invitation.last_name,
                'email': invitation.email,
            },
        )

        # Build menu forms for primary guest and each family member
        primary_menu_form = build_menu_form(event, 'menu_primary', data=request.POST) if has_menu else None

        num_family = len(existing_family_members)
        family_menu_forms = [
            build_menu_form(event, f'menu_family_{i}', data=request.POST)
            for i in range(num_family)
        ] if has_menu else []

        # Validate
        forms_valid = rsvp_form_inst.is_valid()
        if has_menu:
            attending = request.POST.get('rsvp-attending', 'yes')
            if attending == 'yes':
                if not primary_menu_form.is_valid():
                    forms_valid = False
                for family_menu_form in family_menu_forms:
                    if not family_menu_form.is_valid():
                        forms_valid = False

        if forms_valid:
            with transaction.atomic():
                rsvp = rsvp_form_inst.save(commit=False)
                rsvp.event = event
                rsvp.first_name = invitation.first_name
                rsvp.last_name = invitation.last_name
                # Always bind RSVP ownership to the authenticated invitation email.
                rsvp.email = invitation_email
                rsvp.save()

                # Clear previous menu selections (but NOT family members—they're fixed)
                rsvp.menu_selections.all().delete()

                attending = rsvp.attending
                if attending == 'yes' and has_menu and primary_menu_form:
                    _save_menu_selections(primary_menu_form, categories, rsvp=rsvp)

                # Save menu selections for existing family members
                for i, member in enumerate(existing_family_members):
                    if i < len(family_menu_forms):
                        if family_menu_forms[i].is_valid():
                            member.menu_selections.all().delete()
                            _save_menu_selections(family_menu_forms[i], categories, family_member=member)

            messages.success(request, f"Thank you, {rsvp.first_name}! Your RSVP has been saved.")
            return redirect('rsvp_confirmation', rsvp_pk=rsvp.pk)

    else:
        rsvp_form_inst = LockedEmailRSVPForm(
            instance=existing_rsvp,
            prefix='rsvp',
            initial={
                'first_name': invitation.first_name,
                'last_name': invitation.last_name,
                'email': invitation.email,
            },
        )

        # Build menu forms with existing selections pre-populated
        if has_menu:
            primary_initial = _get_menu_initial(rsvp=existing_rsvp, categories=categories) if existing_rsvp else {}
            primary_menu_form = build_menu_form(event, 'menu_primary', initial=primary_initial)

            family_menu_forms = []
            for i, member in enumerate(existing_family_members):
                family_initial = _get_menu_initial(family_member=member, categories=categories)
                family_menu_forms.append(build_menu_form(event, f'menu_family_{i}', initial=family_initial))
        else:
            primary_menu_form = None
            family_menu_forms = []

    context = {
        'event': event,
        'invitation': invitation,
        'rsvp_form': rsvp_form_inst,
        'family_with_menus': zip(existing_family_members, family_menu_forms),
        'primary_menu_form': primary_menu_form,
        'has_menu': has_menu,
        'categories': categories,
        'existing_rsvp': existing_rsvp,
        'menu_categories_json': menu_cats_json,
        'show_personal_info_form': False,
    }
    return render(request, 'rsvp/rsvp_form.html', context)


def _save_menu_selections(menu_form, categories, rsvp=None, family_member=None):
    for category in categories:
        field_name = f'category_{category.pk}'
        if field_name not in menu_form.cleaned_data:
            continue
        value = menu_form.cleaned_data[field_name]
        if not value:
            continue
        pks = value if isinstance(value, list) else [value]
        for pk in pks:
            try:
                item = MenuItem.objects.get(pk=int(pk))
            except (MenuItem.DoesNotExist, ValueError):
                continue
            if rsvp:
                RSVPMenuSelection.objects.get_or_create(rsvp=rsvp, menu_item=item)
            elif family_member:
                FamilyMemberMenuSelection.objects.get_or_create(family_member=family_member, menu_item=item)


def _get_menu_initial(rsvp=None, family_member=None, categories=None):
    """
    Get existing menu selections as initial data for form building.
    Returns dict like {f'category_{cat_id}': [item_id1, item_id2], ...}
    """
    if categories is None:
        categories = []

    initial = {}
    if rsvp:
        for category in categories:
            field_name = f'category_{category.pk}'
            selections = rsvp.menu_selections.filter(
                menu_item__category=category
            ).values_list('menu_item__pk', flat=True)
            if selections:
                # ChoiceField/MultipleChoiceField expect string values
                initial[field_name] = [str(pk) for pk in selections]
    elif family_member:
        if hasattr(family_member, 'menu_selections'):
            for category in categories:
                field_name = f'category_{category.pk}'
                selections = family_member.menu_selections.filter(
                    menu_item__category=category
                ).values_list('menu_item__pk', flat=True)
                if selections:
                    initial[field_name] = [str(pk) for pk in selections]

    return initial


def rsvp_confirmation(request, rsvp_pk):
    invitation_email = _session_invitation_email(request)
    if not invitation_email:
        return HttpResponseForbidden("Forbidden")

    rsvp = get_object_or_404(RSVP, pk=rsvp_pk)
    if rsvp.email.lower() != invitation_email.lower():
        return HttpResponseForbidden("Forbidden")

    return render(request, 'rsvp/confirmation.html', {'rsvp': rsvp})


def invited_rsvp(request, token):
    invitation = get_object_or_404(Invitation, token=token)
    request.session[INVITATION_AUTH_SESSION_KEY] = True
    request.session[INVITATION_EMAIL_SESSION_KEY] = invitation.email

    event = invitation.event

    if not event.is_accepting_rsvps:
        messages.error(request, "The RSVP deadline for this event has passed.")
        return redirect('event_list')

    # If already responded, allow editing
    existing_rsvp = invitation.rsvp

    categories = list(MenuCategory.objects.filter(event=event).prefetch_related('items'))
    has_menu = bool(categories)
    menu_cats_json = _menu_categories_json(categories)

    # Pre-created family members from the invitation
    invited_family = list(invitation.family_members.all())
    # If RSVP already exists, use its family members; otherwise use invitation family
    family_members_to_show = list(existing_rsvp.family_members.all()) if existing_rsvp else invited_family

    if request.method == 'POST':
        form = LockedEmailRSVPForm(
            request.POST,
            instance=existing_rsvp,
            prefix='rsvp',
            initial={'email': invitation.email, 'first_name': invitation.first_name, 'last_name': invitation.last_name},
        )

        primary_menu_form = build_menu_form(event, 'menu_primary', data=request.POST) if has_menu else None
        family_menu_forms = [
            build_menu_form(event, f'menu_family_{i}', data=request.POST)
            for i in range(len(family_members_to_show))
        ] if has_menu else []

        forms_valid = form.is_valid()
        if has_menu:
            attending = request.POST.get('rsvp-attending', 'yes')
            if attending == 'yes':
                if not primary_menu_form.is_valid():
                    forms_valid = False
                for family_menu_form in family_menu_forms:
                    if not family_menu_form.is_valid():
                        forms_valid = False

        if forms_valid:
            with transaction.atomic():
                rsvp = form.save(commit=False)
                rsvp.event = event
                rsvp.first_name = invitation.first_name
                rsvp.last_name = invitation.last_name
                rsvp.email = invitation.email
                rsvp.save()

                rsvp.menu_selections.all().delete()
                rsvp.family_members.all().delete()

                attending = rsvp.attending
                if attending == 'yes' and has_menu and primary_menu_form:
                    _save_menu_selections(primary_menu_form, categories, rsvp=rsvp)

                # Create FamilyMember objects from invited family members and save their menu selections
                family_members = []
                for invited_member in invited_family:
                    member = FamilyMember.objects.create(
                        rsvp=rsvp,
                        first_name=invited_member.first_name,
                        last_name=invited_member.last_name,
                        dietary_notes='',
                    )
                    family_members.append(member)

                # Save menu selections for family members
                for i, member in enumerate(family_members):
                    if i < len(family_menu_forms):
                        if family_menu_forms[i].is_valid():
                            _save_menu_selections(family_menu_forms[i], categories, family_member=member)

                # Link invitation → RSVP (ensure it's set)
                invitation.rsvp = rsvp
                invitation.save(update_fields=['rsvp'])

            messages.success(request, f"Thank you, {rsvp.first_name}! Your RSVP has been saved.")
            return redirect('rsvp_confirmation', rsvp_pk=rsvp.pk)

    else:
        initial_rsvp = {
            'first_name': invitation.first_name,
            'last_name': invitation.last_name,
            'email': invitation.email,
        }
        form = LockedEmailRSVPForm(
            instance=existing_rsvp,
            prefix='rsvp',
            initial=initial_rsvp,
        )

        # Build menu forms with existing selections pre-populated
        if has_menu:
            primary_initial = _get_menu_initial(rsvp=existing_rsvp, categories=categories) if existing_rsvp else {}
            primary_menu_form = build_menu_form(event, 'menu_primary', initial=primary_initial)

            family_menu_forms = []
            for i, member in enumerate(family_members_to_show):
                family_initial = _get_menu_initial(
                    family_member=member,
                    categories=categories,
                ) if hasattr(member, 'menu_selections') else {}
                family_menu_forms.append(build_menu_form(event, f'menu_family_{i}', initial=family_initial))
        else:
            primary_menu_form = None
            family_menu_forms = []

    context = {
        'event': event,
        'invitation': invitation,
        'rsvp_form': form,
        'family_with_menus': zip(family_members_to_show, family_menu_forms),
        'primary_menu_form': primary_menu_form,
        'has_menu': has_menu,
        'categories': categories,
        'existing_rsvp': existing_rsvp,
        'menu_categories_json': menu_cats_json,
        'show_personal_info_form': False,
    }
    return render(request, 'rsvp/rsvp_form.html', context)


def _menu_categories_json(categories):
    return json.dumps(
        [
            {
                'id': cat.pk,
                'name': cat.name,
                'required': cat.required,
                'items': [{'id': item.pk, 'name': item.name} for item in cat.items.all()],
            }
            for cat in categories
        ],
        cls=DjangoJSONEncoder,
    )


def placecards(request, event_pk):
    event = get_object_or_404(Event, pk=event_pk)
    side = request.GET.get('side', 'front').lower()
    if side not in ('front', 'back'):
        side = 'front'
    cards_per_sheet = 10
    categories = list(MenuCategory.objects.filter(event=event).prefetch_related('items'))

    # Build a flat list of attendee dicts and sort by last name for printing.
    attendees = []
    for rsvp in (
        event.rsvps
        .filter(attending='yes')
        .select_related('table')
        .prefetch_related('menu_selections__menu_item__category', 'family_members__table', 'family_members__menu_selections__menu_item__category')
        .order_by('last_name', 'first_name')
    ):
        attendees.append({
            'name': rsvp.full_name,
            'table': rsvp.table.name if rsvp.table else '',
            'menu_choice': _menu_choice_text(rsvp, categories=categories),
            'last_name': rsvp.last_name,
            'first_name': rsvp.first_name,
        })
        for member in rsvp.family_members.all().order_by('last_name', 'first_name'):
            attendees.append({
                'name': member.full_name,
                'table': member.table.name if member.table else (rsvp.table.name if rsvp.table else ''),
                'menu_choice': _menu_choice_text(member, categories=categories),
                'last_name': member.last_name,
                'first_name': member.first_name,
            })

    attendees.sort(key=lambda a: (a['last_name'].lower(), a['first_name'].lower()))

    # Pad to full sheets so front/back print alignment remains consistent.
    padded_attendees = list(attendees)
    remainder = len(padded_attendees) % cards_per_sheet
    if remainder:
        padded_attendees.extend([None] * (cards_per_sheet - remainder))

    sheets = [
        padded_attendees[i:i + cards_per_sheet]
        for i in range(0, len(padded_attendees), cards_per_sheet)
    ]

    return render(request, 'rsvp/placecards.html', {
        'event': event,
        'attendees': attendees,
        'sheets': sheets,
        'side': side,
        'is_back': side == 'back',
    })


def _menu_choice_text(person, categories):
    selections_by_category = {}
    for selection in person.menu_selections.select_related('menu_item', 'menu_item__category').all():
        category = selection.menu_item.category
        selections_by_category.setdefault(category.pk, {
            'category_name': category.name,
            'items': [],
        })['items'].append(selection.menu_item.name)

    if not selections_by_category:
        return ''

    ordered_parts = []
    for category in categories:
        data = selections_by_category.get(category.pk)
        if not data:
            continue
        ordered_parts.append(f"{data['category_name']}: {', '.join(data['items'])}")
    return ' | '.join(ordered_parts)

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.db import transaction
from django.core.serializers.json import DjangoJSONEncoder
import json

from .models import (
    Event, RSVP, RSVPMenuSelection, FamilyMember, FamilyMemberMenuSelection,
    MenuCategory, MenuItem, Invitation,
)
from .forms import RSVPForm, LockedEmailRSVPForm, build_menu_form


def event_list(request):
    events = Event.objects.all().order_by('date')
    return render(request, 'rsvp/event_list.html', {'events': events})


def rsvp_form(request, event_pk):
    event = get_object_or_404(Event, pk=event_pk)

    if not event.is_accepting_rsvps:
        messages.error(request, "The RSVP deadline for this event has passed.")
        return redirect('event_list')

    # Try to pre-populate if the user has already RSVP'd (edit flow via email lookup)
    existing_rsvp = None
    prefill_email = request.GET.get('email', '')
    if prefill_email:
        existing_rsvp = RSVP.objects.filter(event=event, email=prefill_email).first()

    categories = list(MenuCategory.objects.filter(event=event).prefetch_related('items'))
    has_menu = bool(categories)
    menu_cats_json = _menu_categories_json(categories)

    # Existing family members (read-only)
    existing_family_members = []
    if existing_rsvp:
        existing_family_members = list(existing_rsvp.family_members.all())

    if request.method == 'POST':
        rsvp_form_inst = RSVPForm(request.POST, instance=existing_rsvp, prefix='rsvp')

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
        rsvp_form_inst = RSVPForm(instance=existing_rsvp, prefix='rsvp',
                                  initial={'email': prefill_email} if prefill_email else {})
        primary_menu_form = build_menu_form(event, 'menu_primary') if has_menu else None
        family_menu_forms = [
            build_menu_form(event, f'menu_family_{i}')
            for i in range(len(existing_family_members))
        ] if has_menu else []

    context = {
        'event': event,
        'rsvp_form': rsvp_form_inst,
        'family_with_menus': zip(existing_family_members, family_menu_forms),
        'primary_menu_form': primary_menu_form,
        'has_menu': has_menu,
        'categories': categories,
        'existing_rsvp': existing_rsvp,
        'menu_categories_json': menu_cats_json,
        'show_personal_info_form': not existing_rsvp,
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


def rsvp_confirmation(request, rsvp_pk):
    rsvp = get_object_or_404(RSVP, pk=rsvp_pk)
    return render(request, 'rsvp/confirmation.html', {'rsvp': rsvp})


def invited_rsvp(request, token):
    invitation = get_object_or_404(Invitation, token=token)
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

        primary_menu_form = build_menu_form(event, 'menu_primary') if has_menu else None
        family_menu_forms = [
            build_menu_form(event, f'menu_family_{i}')
            for i in range(len(family_members_to_show))
        ] if has_menu else []

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

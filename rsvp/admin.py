from django.contrib import admin, messages as django_messages
from django import forms
from django.urls import reverse
from django.utils.html import format_html
from .models import (
    Event, MenuCategory, MenuItem,
    RSVP, RSVPMenuSelection,
    FamilyMember, FamilyMemberMenuSelection,
    Invitation, InvitedFamilyMember,
    Table,
)
from .mail import send_invitation_email


class TableChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        assigned = obj.seat_count
        if obj.capacity:
            remaining = obj.capacity - assigned
            return f"{obj.name} ({assigned}/{obj.capacity} assigned, {remaining} left)"
        return f"{obj.name} ({assigned} assigned)"


class RSVPAdminForm(forms.ModelForm):
    table = TableChoiceField(queryset=Table.objects.none(), required=False)

    class Meta:
        model = RSVP
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields['table'].queryset = Table.objects.filter(event=self.instance.event)


class FamilyMemberAdminForm(forms.ModelForm):
    table = TableChoiceField(queryset=Table.objects.none(), required=False)

    class Meta:
        model = FamilyMember
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields['table'].queryset = Table.objects.filter(event=self.instance.rsvp.event)


class FamilyMemberInlineForm(forms.ModelForm):
    table = TableChoiceField(queryset=Table.objects.none(), required=False)

    class Meta:
        model = FamilyMember
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields['table'].queryset = Table.objects.filter(event=self.instance.rsvp.event)


class MenuItemInline(admin.TabularInline):
    model = MenuItem
    extra = 1


class MenuCategoryInline(admin.TabularInline):
    model = MenuCategory
    extra = 1
    show_change_link = True


class TableInline(admin.TabularInline):
    model = Table
    extra = 1
    fields = ['name', 'capacity']


@admin.register(Table)
class TableAdmin(admin.ModelAdmin):
    list_display = ['name', 'event', 'capacity', 'seat_count']
    list_filter = ['event']

    def seat_count(self, obj):
        return obj.seat_count
    seat_count.short_description = 'Assigned Seats'


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ['name', 'date', 'location', 'rsvp_deadline', 'rsvp_count', 'invitation_count', 'placecards_link']
    inlines = [MenuCategoryInline, TableInline]

    def rsvp_count(self, obj):
        return obj.rsvps.count()
    rsvp_count.short_description = 'RSVPs'

    def invitation_count(self, obj):
        total = obj.invitations.count()
        sent = obj.invitations.filter(sent_at__isnull=False).count()
        responded = obj.invitations.filter(rsvp__isnull=False).count()
        return f"{responded}/{sent}/{total} (responded/sent/total)"
    invitation_count.short_description = 'Invitations (responded/sent/total)'

    def placecards_link(self, obj):
        url = reverse('placecards', kwargs={'event_pk': obj.pk})
        return format_html('<a href="{}" target="_blank">Print Placecards</a>', url)
    placecards_link.short_description = 'Placecards'


@admin.register(MenuCategory)
class MenuCategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'event', 'required', 'order']
    list_filter = ['event']
    inlines = [MenuItemInline]


@admin.register(MenuItem)
class MenuItemAdmin(admin.ModelAdmin):
    list_display = ['name', 'category', 'is_vegetarian', 'is_vegan', 'is_gluten_free']
    list_filter = ['category__event', 'is_vegetarian', 'is_vegan', 'is_gluten_free']


class RSVPMenuSelectionInline(admin.TabularInline):
    model = RSVPMenuSelection
    extra = 0


class FamilyMemberMenuSelectionInline(admin.TabularInline):
    model = FamilyMemberMenuSelection
    extra = 0


class FamilyMemberInline(admin.StackedInline):
    model = FamilyMember
    form = FamilyMemberInlineForm
    extra = 0
    show_change_link = True

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'table':
            obj_id = request.resolver_match.kwargs.get('object_id') if request.resolver_match else None
            if obj_id:
                try:
                    rsvp_obj = RSVP.objects.select_related('event').get(pk=obj_id)
                    kwargs['queryset'] = Table.objects.filter(event=rsvp_obj.event)
                except RSVP.DoesNotExist:
                    kwargs['queryset'] = Table.objects.none()
            else:
                kwargs['queryset'] = Table.objects.none()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(RSVP)
class RSVPAdmin(admin.ModelAdmin):
    form = RSVPAdminForm
    list_display = ['full_name', 'email', 'event', 'attending', 'table', 'total_guests', 'submitted_at']
    list_filter = ['event', 'attending', 'table']
    list_editable = ['table']
    search_fields = ['first_name', 'last_name', 'email']
    readonly_fields = ['submitted_at', 'updated_at']
    inlines = [RSVPMenuSelectionInline, FamilyMemberInline]

    def full_name(self, obj):
        return obj.full_name
    full_name.short_description = 'Name'
    full_name.admin_order_field = 'last_name'

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'table':
            obj_id = request.resolver_match.kwargs.get('object_id') if request.resolver_match else None
            if obj_id:
                try:
                    rsvp_obj = RSVP.objects.select_related('event').get(pk=obj_id)
                    kwargs['queryset'] = Table.objects.filter(event=rsvp_obj.event)
                except RSVP.DoesNotExist:
                    kwargs['queryset'] = Table.objects.none()
            else:
                event_id = request.GET.get('event__id__exact')
                if event_id:
                    kwargs['queryset'] = Table.objects.filter(event_id=event_id)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def get_changelist_formset(self, request, **kwargs):
        FormSet = super().get_changelist_formset(request, **kwargs)
        table_field = FormSet.form.base_fields.get('table')
        if table_field:
            table_field.__class__ = TableChoiceField
            event_id = request.GET.get('event__id__exact')
            if event_id:
                table_field.queryset = Table.objects.filter(event_id=event_id)
            else:
                table_field.queryset = Table.objects.none()
        return FormSet


@admin.register(FamilyMember)
class FamilyMemberAdmin(admin.ModelAdmin):
    form = FamilyMemberAdminForm
    list_display = ['full_name', 'rsvp', 'table', 'dietary_notes']
    list_filter = ['rsvp__event', 'table']
    list_editable = ['table']
    search_fields = ['first_name', 'last_name', 'rsvp__email']
    inlines = [FamilyMemberMenuSelectionInline]

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'table':
            obj_id = request.resolver_match.kwargs.get('object_id') if request.resolver_match else None
            if obj_id:
                try:
                    member_obj = FamilyMember.objects.select_related('rsvp__event').get(pk=obj_id)
                    kwargs['queryset'] = Table.objects.filter(event=member_obj.rsvp.event)
                except FamilyMember.DoesNotExist:
                    kwargs['queryset'] = Table.objects.none()
            else:
                event_id = request.GET.get('rsvp__event__id__exact')
                if event_id:
                    kwargs['queryset'] = Table.objects.filter(event_id=event_id)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def get_changelist_formset(self, request, **kwargs):
        FormSet = super().get_changelist_formset(request, **kwargs)
        table_field = FormSet.form.base_fields.get('table')
        if table_field:
            table_field.__class__ = TableChoiceField
            event_id = request.GET.get('rsvp__event__id__exact')
            if event_id:
                table_field.queryset = Table.objects.filter(event_id=event_id)
            else:
                table_field.queryset = Table.objects.none()
        return FormSet


class InvitedFamilyMemberInline(admin.TabularInline):
    model = InvitedFamilyMember
    extra = 1
    fields = ['first_name', 'last_name']


@admin.register(Invitation)
class InvitationAdmin(admin.ModelAdmin):
    list_display = [
        'full_name', 'email', 'event', 'family_member_count',
        'sent_at', 'has_responded', 'rsvp_link_display',
    ]
    list_filter = ['event', 'sent_at']
    search_fields = ['first_name', 'last_name', 'email']
    readonly_fields = ['token', 'sent_at', 'rsvp', 'rsvp_link_display']
    inlines = [InvitedFamilyMemberInline]
    actions = ['send_invitations', 'resend_invitations']

    def full_name(self, obj):
        return obj.full_name
    full_name.short_description = 'Name'

    def family_member_count(self, obj):
        return obj.family_members.count()
    family_member_count.short_description = 'Pre-added Guests'

    def has_responded(self, obj):
        return obj.has_responded
    has_responded.boolean = True
    has_responded.short_description = 'RSVP\'d?'

    def rsvp_link_display(self, obj):
        path = obj.get_rsvp_path()
        return format_html('<a href="{}" target="_blank">{}</a>', path, path)
    rsvp_link_display.short_description = 'RSVP Link (path)'

    @admin.action(description='Send invitation emails (skip already sent)')
    def send_invitations(self, request, queryset):
        unsent = queryset.filter(sent_at__isnull=True)
        self._do_send(request, unsent)

    @admin.action(description='Re-send invitation emails (including already sent)')
    def resend_invitations(self, request, queryset):
        self._do_send(request, queryset)

    def _do_send(self, request, queryset):
        sent_count = 0
        error_count = 0
        for invitation in queryset.prefetch_related('family_members'):
            rsvp_url = request.build_absolute_uri(invitation.get_rsvp_path())
            try:
                send_invitation_email(invitation, rsvp_url)
                sent_count += 1
            except Exception as exc:
                error_count += 1
                self.message_user(
                    request,
                    f"Failed to send to {invitation.email}: {exc}",
                    level=django_messages.ERROR,
                )
        if sent_count:
            self.message_user(request, f"Sent {sent_count} invitation(s).")
        if error_count:
            self.message_user(
                request,
                f"{error_count} invitation(s) failed.",
                level=django_messages.WARNING,
            )

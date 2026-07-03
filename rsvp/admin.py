from django.contrib import admin, messages as django_messages
from django.utils.html import format_html
from .models import (
    Event, MenuCategory, MenuItem,
    RSVP, RSVPMenuSelection,
    FamilyMember, FamilyMemberMenuSelection,
    Invitation, InvitedFamilyMember,
)
from .mail import send_invitation_email


class MenuItemInline(admin.TabularInline):
    model = MenuItem
    extra = 1


class MenuCategoryInline(admin.TabularInline):
    model = MenuCategory
    extra = 1
    show_change_link = True


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ['name', 'date', 'location', 'rsvp_deadline', 'rsvp_count', 'invitation_count']
    inlines = [MenuCategoryInline]

    def rsvp_count(self, obj):
        return obj.rsvps.count()
    rsvp_count.short_description = 'RSVPs'

    def invitation_count(self, obj):
        total = obj.invitations.count()
        sent = obj.invitations.filter(sent_at__isnull=False).count()
        responded = obj.invitations.filter(rsvp__isnull=False).count()
        return f"{responded}/{sent}/{total} (responded/sent/total)"
    invitation_count.short_description = 'Invitations (responded/sent/total)'


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
    extra = 0
    show_change_link = True


@admin.register(RSVP)
class RSVPAdmin(admin.ModelAdmin):
    list_display = ['full_name', 'email', 'event', 'attending', 'total_guests', 'submitted_at']
    list_filter = ['event', 'attending']
    search_fields = ['first_name', 'last_name', 'email']
    readonly_fields = ['submitted_at', 'updated_at']
    inlines = [RSVPMenuSelectionInline, FamilyMemberInline]


@admin.register(FamilyMember)
class FamilyMemberAdmin(admin.ModelAdmin):
    list_display = ['full_name', 'rsvp', 'dietary_notes']
    list_filter = ['rsvp__event']
    search_fields = ['first_name', 'last_name', 'rsvp__email']
    inlines = [FamilyMemberMenuSelectionInline]


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

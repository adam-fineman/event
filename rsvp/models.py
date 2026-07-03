import uuid
from django.db import models
from django.urls import reverse
from django.utils import timezone


class Event(models.Model):
    name = models.CharField(max_length=200)
    date = models.DateTimeField()
    location = models.CharField(max_length=300)
    description = models.TextField(blank=True)
    rsvp_deadline = models.DateTimeField(null=True, blank=True)
    max_guests = models.PositiveIntegerField(null=True, blank=True, help_text="Leave blank for unlimited")

    def __str__(self):
        return self.name

    @property
    def is_accepting_rsvps(self):
        if self.rsvp_deadline:
            return timezone.now() <= self.rsvp_deadline
        return True


class MenuCategory(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='menu_categories')
    name = models.CharField(max_length=100, help_text="e.g. Entrée, Dessert, Dietary Preference")
    required = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order', 'name']
        verbose_name_plural = 'Menu Categories'

    def __str__(self):
        return f"{self.event.name} — {self.name}"


class MenuItem(models.Model):
    category = models.ForeignKey(MenuCategory, on_delete=models.CASCADE, related_name='items')
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    is_vegetarian = models.BooleanField(default=False)
    is_vegan = models.BooleanField(default=False)
    is_gluten_free = models.BooleanField(default=False)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order', 'name']

    def __str__(self):
        return self.name


class RSVP(models.Model):
    ATTENDING_CHOICES = [
        ('yes', 'Yes, I will attend'),
        ('no', 'No, I cannot attend'),
        ('maybe', 'Maybe'),
    ]

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='rsvps')
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField()
    phone = models.CharField(max_length=20, blank=True)
    attending = models.CharField(max_length=5, choices=ATTENDING_CHOICES, default='yes')
    dietary_notes = models.TextField(blank=True, help_text="Allergies or other dietary requirements")
    submitted_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('event', 'email')
        ordering = ['-submitted_at']

    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.event.name})"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    @property
    def total_guests(self):
        return 1 + self.family_members.count()


class RSVPMenuSelection(models.Model):
    rsvp = models.ForeignKey(RSVP, on_delete=models.CASCADE, related_name='menu_selections')
    menu_item = models.ForeignKey(MenuItem, on_delete=models.CASCADE)

    class Meta:
        unique_together = ('rsvp', 'menu_item')

    def __str__(self):
        return f"{self.rsvp.full_name} → {self.menu_item.name}"


class FamilyMember(models.Model):
    rsvp = models.ForeignKey(RSVP, on_delete=models.CASCADE, related_name='family_members')
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    dietary_notes = models.TextField(blank=True)

    def __str__(self):
        return f"{self.first_name} {self.last_name} (guest of {self.rsvp.full_name})"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"


class FamilyMemberMenuSelection(models.Model):
    family_member = models.ForeignKey(FamilyMember, on_delete=models.CASCADE, related_name='menu_selections')
    menu_item = models.ForeignKey(MenuItem, on_delete=models.CASCADE)

    class Meta:
        unique_together = ('family_member', 'menu_item')

    def __str__(self):
        return f"{self.family_member.full_name} → {self.menu_item.name}"


class Invitation(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='invitations')
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False, db_index=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField()
    sent_at = models.DateTimeField(null=True, blank=True)
    rsvp = models.OneToOneField(
        RSVP, null=True, blank=True, on_delete=models.SET_NULL, related_name='invitation'
    )

    class Meta:
        unique_together = ('event', 'email')
        ordering = ['last_name', 'first_name']

    def __str__(self):
        return f"{self.first_name} {self.last_name} <{self.email}>"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    def get_rsvp_path(self):
        return reverse('invited_rsvp', kwargs={'token': self.token})

    @property
    def has_responded(self):
        return self.rsvp_id is not None


class InvitedFamilyMember(models.Model):
    """Family members pre-created by the event organiser for an invitee."""
    invitation = models.ForeignKey(Invitation, on_delete=models.CASCADE, related_name='family_members')
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)

    class Meta:
        ordering = ['last_name', 'first_name']

    def __str__(self):
        return f"{self.first_name} {self.last_name}"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

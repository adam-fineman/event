import uuid

from django.contrib.admin.sites import AdminSite
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .admin import RSVPAdmin
from .models import Event, Invitation, MenuCategory, MenuItem, RSVP, RSVPMenuSelection


class RSVPAdminTests(TestCase):
    def test_rsvp_admin_full_name_is_configured_for_sorting(self):
        admin = RSVPAdmin(RSVP, AdminSite())
        self.assertEqual(admin.full_name.short_description, 'Name')
        self.assertEqual(admin.full_name.admin_order_field, 'last_name')


class EventListAccessTests(TestCase):
    def setUp(self):
        self.event = Event.objects.create(
            name='Test Event',
            date=timezone.now() + timezone.timedelta(days=7),
            location='Test Venue',
        )
        self.other_event = Event.objects.create(
            name='Other Event',
            date=timezone.now() + timezone.timedelta(days=10),
            location='Other Venue',
        )
        self.invitation = Invitation.objects.create(
            event=self.event,
            token=uuid.uuid4(),
            first_name='Jordan',
            last_name='Guest',
            email='jordan@example.com',
        )
        Invitation.objects.create(
            event=self.other_event,
            token=uuid.uuid4(),
            first_name='Casey',
            last_name='Else',
            email='casey@example.com',
        )

    def test_homepage_returns_403_without_invitation_authenticated_session(self):
        response = self.client.get(reverse('event_list'))
        self.assertEqual(response.status_code, 403)

    def test_invitation_link_sets_session_and_allows_homepage(self):
        invite_url = reverse('invited_rsvp', kwargs={'token': self.invitation.token})
        invite_response = self.client.get(invite_url)
        self.assertEqual(invite_response.status_code, 200)

        response = self.client.get(reverse('event_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Test Event')
        self.assertNotContains(response, 'Other Event')

    def test_rsvp_form_returns_403_for_event_without_invitation_for_session_email(self):
        invite_url = reverse('invited_rsvp', kwargs={'token': self.invitation.token})
        self.client.get(invite_url)

        response = self.client.get(reverse('rsvp_form', kwargs={'event_pk': self.other_event.pk}))
        self.assertEqual(response.status_code, 403)

    def test_rsvp_form_for_invited_event_forces_session_email(self):
        invite_url = reverse('invited_rsvp', kwargs={'token': self.invitation.token})
        self.client.get(invite_url)

        response = self.client.post(
            reverse('rsvp_form', kwargs={'event_pk': self.event.pk}),
            {
                'rsvp-first_name': 'Jordan',
                'rsvp-last_name': 'Guest',
                'rsvp-email': 'attacker@example.com',
                'rsvp-attending': 'yes',
                'rsvp-phone': '',
                'rsvp-dietary_notes': '',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        rsvp = RSVP.objects.get(event=self.event)
        self.assertEqual(rsvp.email, 'jordan@example.com')
        self.assertEqual(rsvp.first_name, 'Jordan')
        self.assertEqual(rsvp.last_name, 'Guest')

    def test_rsvp_form_does_not_render_editable_name_or_email_fields(self):
        invite_url = reverse('invited_rsvp', kwargs={'token': self.invitation.token})
        self.client.get(invite_url)

        response = self.client.get(reverse('rsvp_form', kwargs={'event_pk': self.event.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'name="rsvp-first_name"')
        self.assertNotContains(response, 'name="rsvp-last_name"')
        self.assertNotContains(response, 'name="rsvp-email"')


class InvitationDeletionTests(TestCase):
    def setUp(self):
        self.event = Event.objects.create(
            name='Test Event',
            date=timezone.now() + timezone.timedelta(days=7),
            location='Test Venue',
        )

    def _create_invitation_with_rsvp(self, email):
        rsvp = RSVP.objects.create(
            event=self.event,
            first_name='Jordan',
            last_name='Guest',
            email=email,
            attending='yes',
        )
        return Invitation.objects.create(
            event=self.event,
            token=uuid.uuid4(),
            first_name='Jordan',
            last_name='Guest',
            email=email,
            rsvp=rsvp,
        )

    def test_deleting_single_invitation_deletes_linked_rsvp(self):
        invitation = self._create_invitation_with_rsvp('single@example.com')
        rsvp_id = invitation.rsvp_id

        invitation.delete()

        self.assertFalse(RSVP.objects.filter(id=rsvp_id).exists())

    def test_bulk_deleting_invitations_deletes_linked_rsvps(self):
        first = self._create_invitation_with_rsvp('bulk1@example.com')
        second = self._create_invitation_with_rsvp('bulk2@example.com')
        rsvp_ids = [first.rsvp_id, second.rsvp_id]

        Invitation.objects.filter(id__in=[first.id, second.id]).delete()

        self.assertEqual(RSVP.objects.filter(id__in=rsvp_ids).count(), 0)


class PlacecardsTests(TestCase):
    def setUp(self):
        self.event = Event.objects.create(
            name='Test Event',
            date=timezone.now() + timezone.timedelta(days=7),
            location='Test Venue',
        )
        self.entrée_category = MenuCategory.objects.create(
            event=self.event,
            name='Entrée',
            required=True,
            order=1,
        )
        self.chicken = MenuItem.objects.create(
            category=self.entrée_category,
            name='Grilled Chicken',
            order=1,
        )
        self.salmon = MenuItem.objects.create(
            category=self.entrée_category,
            name='Grilled Salmon',
            order=2,
        )

    def test_back_side_placecards_rows_are_mirrored_for_print_alignment(self):
        barnett = RSVP.objects.create(
            event=self.event,
            first_name='Barnett',
            last_name='Davis',
            email='barnett@example.com',
            attending='yes',
        )
        netta = RSVP.objects.create(
            event=self.event,
            first_name='Netta',
            last_name='Davis',
            email='netta@example.com',
            attending='yes',
        )

        RSVPMenuSelection.objects.create(rsvp=barnett, menu_item=self.chicken)
        RSVPMenuSelection.objects.create(rsvp=netta, menu_item=self.salmon)

        response = self.client.get(
            reverse('placecards', kwargs={'event_pk': self.event.pk}) + '?side=back'
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['sheets'][0][0]['name'], 'Netta Davis')
        self.assertEqual(response.context['sheets'][0][0]['menu_choice'], 'Entrée: Grilled Salmon')
        self.assertEqual(response.context['sheets'][0][1]['name'], 'Barnett Davis')
        self.assertEqual(response.context['sheets'][0][1]['menu_choice'], 'Entrée: Grilled Chicken')

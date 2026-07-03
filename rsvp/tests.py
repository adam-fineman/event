import uuid

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Event, Invitation, RSVP


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

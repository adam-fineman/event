from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone


def send_invitation_email(invitation, rsvp_url):
    """
    Send an invitation email for the given Invitation instance.
    rsvp_url must be an absolute URL (built by the caller via request.build_absolute_uri).
    Returns True on success, raises on failure.
    """
    family_members = list(invitation.family_members.all())
    context = {
        'invitation': invitation,
        'rsvp_url': rsvp_url,
        'family_members': family_members,
    }

    subject = f"You're invited: {invitation.event.name}"
    text_body = render_to_string('rsvp/email/invitation.txt', context)
    html_body = render_to_string('rsvp/email/invitation.html', context)

    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        to=[invitation.email],
    )
    msg.attach_alternative(html_body, 'text/html')
    msg.send()

    invitation.sent_at = timezone.now()
    invitation.save(update_fields=['sent_at'])
    return True

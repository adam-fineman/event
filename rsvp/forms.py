from django import forms
from django.forms import formset_factory

from .models import RSVP, FamilyMember, MenuCategory, MenuItem


class RSVPForm(forms.ModelForm):
    class Meta:
        model = RSVP
        fields = ['first_name', 'last_name', 'email', 'phone', 'attending', 'dietary_notes']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'First name'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Last name'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'email@example.com'}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Optional'}),
            'attending': forms.Select(attrs={'class': 'form-select'}),
            'dietary_notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'Allergies, restrictions, etc.',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # If editing an existing RSVP, remove personal info fields from form
        # (they will be displayed as plain text in template)
        instance = getattr(self, 'instance', None)
        if instance and instance.pk:
            del self.fields['first_name']
            del self.fields['last_name']
            del self.fields['email']


class LockedEmailRSVPForm(forms.ModelForm):
    """Invitation flow: name/email fields are removed from form and displayed as text."""
    class Meta:
        model = RSVP
        fields = ['phone', 'attending', 'dietary_notes']
        widgets = {
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Optional'}),
            'attending': forms.Select(attrs={'class': 'form-select'}),
            'dietary_notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'Allergies, restrictions, etc.',
            }),
        }



def build_menu_form(event, person_prefix, data=None, initial=None):
    """
    Dynamically build a form class with one radio/checkbox field per MenuCategory
    for the given event. Returns a bound or unbound form instance.
    """
    fields = {}
    categories = MenuCategory.objects.filter(event=event).prefetch_related('items')

    for category in categories:
        items = category.items.all()
        choices = []
        for item in items:
            description = item.description.strip()
            veg_label = 'Yes' if item.is_vegetarian else 'No'
            if description:
                label = f"{item.name} - {description} (Vegetarian: {veg_label})"
            else:
                label = f"{item.name} (Vegetarian: {veg_label})"
            choices.append((item.pk, label))
        label = category.name
        if category.required:
            fields[f'category_{category.pk}'] = forms.ChoiceField(
                label=label,
                choices=choices,
                widget=forms.RadioSelect(attrs={'class': 'form-check-input'}),
                required=True,
            )
        else:
            fields[f'category_{category.pk}'] = forms.MultipleChoiceField(
                label=label,
                choices=choices,
                widget=forms.CheckboxSelectMultiple(attrs={'class': 'form-check-input'}),
                required=False,
            )

    DynamicMenuForm = type('DynamicMenuForm', (forms.BaseForm,), {'base_fields': fields})
    return DynamicMenuForm(data=data, initial=initial, prefix=person_prefix)


class FamilyMemberForm(forms.ModelForm):
    class Meta:
        model = FamilyMember
        fields = ['first_name', 'last_name', 'dietary_notes']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'First name'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Last name'}),
            'dietary_notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'Allergies, restrictions, etc.',
            }),
        }


FamilyMemberFormSet = formset_factory(FamilyMemberForm, extra=0, can_delete=True)


def make_family_formset(extra=0):
    """Return a formset class with a given number of extra (pre-populated) forms."""
    return formset_factory(FamilyMemberForm, extra=extra, can_delete=True)

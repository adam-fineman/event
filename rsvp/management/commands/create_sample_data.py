from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from rsvp.models import Event, MenuCategory, MenuItem


class Command(BaseCommand):
    help = 'Create sample event data for development'

    def handle(self, *args, **options):
        event, created = Event.objects.get_or_create(
            name="Annual Family Reunion 2026",
            defaults={
                'date': timezone.now() + timedelta(days=60),
                'location': '123 Park Ave, Springfield',
                'description': 'Join us for our annual family reunion! Food, fun, and festivities for all ages.',
                'rsvp_deadline': timezone.now() + timedelta(days=45),
            }
        )

        if created:
            self.stdout.write(self.style.SUCCESS(f'Created event: {event.name}'))

            entree_cat = MenuCategory.objects.create(event=event, name='Entrée', required=True, order=1)
            MenuItem.objects.create(category=entree_cat, name='Grilled Chicken', description='Herb-marinated chicken breast', order=1)
            MenuItem.objects.create(category=entree_cat, name='Beef Brisket', description='Slow-smoked BBQ brisket', order=2)
            MenuItem.objects.create(category=entree_cat, name='Vegetable Lasagna', description='Layered pasta with seasonal vegetables', is_vegetarian=True, order=3)
            MenuItem.objects.create(category=entree_cat, name='Grilled Salmon', description='Atlantic salmon with lemon butter', order=4)

            sides_cat = MenuCategory.objects.create(event=event, name='Side Dishes', required=False, order=2)
            MenuItem.objects.create(category=sides_cat, name='Caesar Salad', is_vegetarian=True, order=1)
            MenuItem.objects.create(category=sides_cat, name='Roasted Vegetables', is_vegetarian=True, is_vegan=True, order=2)
            MenuItem.objects.create(category=sides_cat, name='Mashed Potatoes', is_vegetarian=True, order=3)
            MenuItem.objects.create(category=sides_cat, name='Corn on the Cob', is_vegetarian=True, is_vegan=True, order=4)

            dessert_cat = MenuCategory.objects.create(event=event, name='Dessert', required=True, order=3)
            MenuItem.objects.create(category=dessert_cat, name='Chocolate Cake', order=1)
            MenuItem.objects.create(category=dessert_cat, name='Fruit Tart', is_vegetarian=True, order=2)
            MenuItem.objects.create(category=dessert_cat, name='Ice Cream', is_vegetarian=True, order=3)
            MenuItem.objects.create(category=dessert_cat, name='No Dessert', order=4)

            self.stdout.write(self.style.SUCCESS('Created menu categories and items'))
        else:
            self.stdout.write(self.style.WARNING(f'Event already exists: {event.name}'))

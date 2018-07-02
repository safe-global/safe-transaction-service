from django.test import TestCase
from faker import Faker

from ..singleton import singleton

faker = Faker()

@singleton
class MyClass:
    def __init__(self, name):
        self.name = name


class TestSigning(TestCase):

    def test_singleton(self):
        name = faker.name()
        my_class = MyClass(name)

        another_name = faker.name()
        my_other_class = MyClass(another_name)

        self.assertEqual(my_class.name, my_other_class.name)

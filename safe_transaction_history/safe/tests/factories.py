import os
from logging import getLogger

from ethereum.transactions import secpk1n
from faker import Factory as FakerFactory
from faker import Faker

fakerFactory = FakerFactory.create()
faker = Faker()

logger = getLogger(__name__)

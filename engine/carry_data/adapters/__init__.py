"""FX carry source adapters."""
from .base import BaseSourceAdapter, SourceAcquisitionError
from .new_york_fed import NewYorkFedAdapter
from .ecb import EcbAdapter
from .bank_of_england import BankOfEnglandAdapter
from .bank_of_japan import BankOfJapanAdapter
from .rba import RbaAdapter
from .fred import FredAdapter

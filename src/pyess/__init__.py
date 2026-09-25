"""py-ess: dynamically load and index European Social Survey (ESS) data.

Typical usage::

    from pyess import ESS

    ess = ESS()
    codebook = ess.codebook
    datafile = codebook.find_datafile("ESS11")
    dataset = ess.load(datafile.doi)

    dataset["netuse"].to_json()          # variable metadata + values, JSON-serializable
    dataset.to_dict()                    # whole dataset as nested dict/JSON
"""

from .client import ESS
from .codebook import Codebook, Datafile, Round
from .dataset import Dataset
from .models import ValueLabel, Variable
from .userid import get_user_id

__all__ = [
    "ESS",
    "Codebook",
    "Datafile",
    "Dataset",
    "Round",
    "ValueLabel",
    "Variable",
    "get_user_id",
]

__version__ = "0.1.0"

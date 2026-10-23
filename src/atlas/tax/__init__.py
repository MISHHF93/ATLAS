"""Canadian tax-tracking module (record keeping for a CPA). NOT TAX ADVICE.

ACB: average cost per identical property, pooled per TAXPAYER across all venues
and non-registered accounts, in CAD. Superficial loss: +/-30 days across
affiliated entities. See README "Tax module" for scope and limitations."""
from atlas.tax.engine import TaxEngine, TaxReport  # noqa: F401
from atlas.tax.entities import Entity, Affiliations  # noqa: F401
from atlas.tax.events import Dividend, Income, Swap, Trade, Transfer  # noqa: F401
from atlas.tax.fx import BocFxProvider, FxQuote  # noqa: F401

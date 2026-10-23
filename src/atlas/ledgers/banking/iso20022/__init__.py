"""ISO 20022 messages (SIMULATION / OFFLINE): camt.053/camt.054 parsing (bank statements / debit-credit
notifications), pain.001 generation (customer credit transfer initiation) and pain.002 parsing (payment status
report). Official message versions: pain.001.001.09, pain.002.001.10, camt.053.001.08, camt.054.001.08 (XSDs bundled
under xsd/, from https://www.iso20022.org/iso-20022-message-definitions). Validation = always-on structural checks +
full XSD validation when the optional `xmlschema` package is installed (pure Python, offline)."""
from atlas.ledgers.banking.iso20022.common import XMLError, validate, xsd_available

__all__ = ["XMLError", "validate", "xsd_available"]

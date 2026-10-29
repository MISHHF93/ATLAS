"""News & filings intelligence (evo-14): official sources -> per-ticker items -> rules + optional LLM annotation -> chart layer 26,
a per-user News feed, point-in-time training features, and an LLM *Reviewer* that can only make a proposal more conservative.

Everything here is advisory: ``execution_permission`` is always ``none`` and nothing imports the order path."""
EXECUTION_PERMISSION = "none"

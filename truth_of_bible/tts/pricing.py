"""Google Cloud TTS list prices per voice tier — the one place both admin
screens (usage/billing and the voice comparison) read pricing from, so
cost is computed from the tier a request actually used rather than the
single hand-entered TOB TTS Provider.price_per_million_chars_usd (which
defaults to 0 and only describes one tier).

Source: https://cloud.google.com/text-to-speech/pricing (checked
2026-10). Free characters reset monthly per billing account. Update this
table when Google changes its pricing."""

TIERS = [
	{
		"tier": "Standard",
		"price_per_million_usd": 4.0,
		"free_chars_per_month": 4_000_000,
		"description": "Basic synthetic voice. Cheapest; noticeably robotic.",
	},
	{
		"tier": "WaveNet",
		"price_per_million_usd": 4.0,
		"free_chars_per_month": 4_000_000,
		"description": "DeepMind WaveNet. More natural than Standard at the same price.",
	},
	{
		"tier": "Neural2",
		"price_per_million_usd": 16.0,
		"free_chars_per_month": 1_000_000,
		"description": "Custom-voice technology; natural prosody.",
	},
	{
		"tier": "Polyglot",
		"price_per_million_usd": 16.0,
		"free_chars_per_month": 1_000_000,
		"description": "One voice that speaks several languages.",
	},
	{
		"tier": "Chirp HD",
		"price_per_million_usd": 30.0,
		"free_chars_per_month": 1_000_000,
		"description": "LLM-based HD voices.",
	},
	{
		"tier": "Chirp 3 HD",
		"price_per_million_usd": 30.0,
		"free_chars_per_month": 1_000_000,
		"description": "Newest and most natural voices.",
	},
	{
		"tier": "Studio",
		"price_per_million_usd": 160.0,
		"free_chars_per_month": 1_000_000,
		"description": "Professional narration quality. Most expensive.",
	},
]

_BY_TIER = {t["tier"].lower(): t for t in TIERS}

# Voice-name fragment -> tier. Order matters: "Chirp3-HD" before "Chirp-HD".
_NAME_MARKERS = [
	("chirp3-hd", "Chirp 3 HD"),
	("chirp-hd", "Chirp HD"),
	("journey", "Chirp HD"),  # Journey voices were renamed Chirp HD
	("studio", "Studio"),
	("polyglot", "Polyglot"),
	("neural2", "Neural2"),
	("wavenet", "WaveNet"),
	("standard", "Standard"),
]


def tier_for_voice_name(name: str) -> str:
	"""'ta-IN-Chirp3-HD-Achernar' -> 'Chirp 3 HD'. 'Other' when the name
	matches no known tier (e.g. a newly launched family)."""
	lowered = (name or "").lower()
	for marker, tier in _NAME_MARKERS:
		if marker in lowered:
			return tier
	return "Other"


def tier_info(tier: str | None) -> dict | None:
	"""The TIERS row for a tier name, case-insensitive. TOB TTS Provider's
	voice_type options spell it 'WaveNet'/'Neural2'/..., which match."""
	return _BY_TIER.get((tier or "").lower())


def price_per_million(tier: str | None) -> float:
	info = tier_info(tier)
	return info["price_per_million_usd"] if info else 0.0

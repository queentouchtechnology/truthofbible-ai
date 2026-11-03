"""Articles made before the autopilot sent its image prompt have a blank Cover Image Prompt. Rebuild it the way the
autopilot does (marketing-ai-os build_tob_autopilot_wf.py): the theme's scene, the cover style, and the verse and
reference, which the Image Description already holds as "<ref> — <verse>"."""

import re

import frappe

THEME_SCENES = {  # same scenes as the autopilot's THEMES
	"hope": "A sunrise breaking through clouds over green hills, warm golden light",
	"strength": "An eagle-height view of rugged mountains above the clouds at sunrise, no birds",
	"fear": "A lighthouse beam over calm evening sea after a storm, soft clouds",
	"anxi": "A lighthouse beam over calm evening sea after a storm, soft clouds",
	"grief": "Soft morning light through trees onto a quiet garden path, dew, gentle",
	"comfort": "Soft morning light through trees onto a quiet garden path, dew, gentle",
	"trust": "A winding path through a forest lit by early sun rays",
	"guid": "A winding path through a forest lit by early sun rays",
	"forgiv": "A calm river flowing through a valley at golden hour, clear water",
	"joy": "A sunlit field of yellow flowers under a bright blue sky",
	"care": "Green pastures beside still waters in soft morning light",
	"shepherd": "Green pastures beside still waters in soft morning light",
	"patien": "A single tree on a hill at dawn with mist in the valley",
	"wait": "A single tree on a hill at dawn with mist in the valley",
	"new": "First light of morning over the ocean horizon, pastel sky",
	"faith": "A path of stepping stones across a calm stream at sunrise",
	"grace": "Golden light streaming through clouds onto a quiet valley",
	"pray": "An open window with soft morning light and a candle on the sill, no people",
	"kind": "Warm sunlight over a village path lined with flowers, no people",
	"compassion": "Warm sunlight over a village path lined with flowers, no people",
}
HEROES = ["Hannah", "Samson", "Simson", "Moses", "Saul", "Jeremiah", "Nehemiah", "Ezekiel", "Mordecai", "Noah",
	"Shunammite", "Samuel", "Joseph", "Deborah", "Jehoshaphat"]
STYLE = ("Photorealistic, calm, uplifting. Soft, muted, slightly dim cinematic light with gentle contrast and darker edges, "
	"like the site's other covers — not bright or oversaturated. Absolutely NO people, faces, figures or animals. ")


def _scene(a) -> str:
	text = f"{a.title} {a.slug}".lower()
	if a.kind == "course" or any(h.lower() in text for h in HEROES):
		hero = next((h for h in HEROES if h.lower() in text), "the Bible story")
		return f"A calm, reverent landscape inspired by the biblical setting of {hero}, ancient land, soft natural light"
	for key, scene in THEME_SCENES.items():
		if re.search(rf"\b{key}", text):
			return scene
	return "Golden light streaming through clouds onto a quiet valley"


def prompt_for(a) -> str:
	prompt = f"{_scene(a)}. {STYLE}"
	ref, sep, verse = (a.image_alt or "").partition(" — ")
	if sep and verse.strip():
		prompt += (f"In the centre, in large elegant white serif lettering with a soft dark shadow, exactly this text and "
			f"nothing else: “{verse.strip()}” and below it in smaller gold italic: {ref.strip()}. ")
	return prompt + "At the bottom, small white text: truthofbible.org. Spell every word exactly as given. Leave generous margins."


def execute():
	for a in frappe.get_all("TOB Article", filters={"image_prompt": ["in", ["", None]]},
			fields=["name", "title", "slug", "kind", "image_alt"]):
		frappe.db.set_value("TOB Article", a.name, "image_prompt", prompt_for(a), update_modified=False)

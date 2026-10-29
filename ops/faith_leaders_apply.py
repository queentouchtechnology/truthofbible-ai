"""Publish the Faith Leaders lessons built by faith_leaders_build.py.

In every chapter it removes only the generated lessons (Read / Short Lesson / Brief Lesson, created by this
tooling on 2026-10-29) and puts the built "Lesson from <leader>" first. The chapters' own lessons are never
edited or deleted; their link rows keep their order after the new lesson. Safe to re-run.

    cd /home/frappe/frappe-bench/sites && ../env/bin/python faith_leaders_apply.py lessons.json [--apply]
"""
import sys

COURSE = "faith-leaders-learning-faith-through-bible-heroes"
SITE = "learn.truthofbible.org"
GENERATED_SINCE = "2026-10-29 17:40:00"


def is_generated(frappe, lesson):
    title, created = frappe.db.get_value("Course Lesson", lesson, ["title", "creation"])
    return (title.startswith("Read: ") or title in ("Short Lesson (Adults)", "Brief Lesson (All Ages)")) \
        and str(created) >= GENERATED_SINCE


def main(path, apply):
    import json
    import frappe
    frappe.init(site=SITE, sites_path=".")
    frappe.connect()
    frappe.set_user("Administrator")
    built = {b["chapter"]: b for b in json.load(open(path, encoding="utf-8"))}
    chapters = frappe.get_all("Chapter Reference", filters={"parent": COURSE}, fields=["chapter", "idx"], order_by="idx")
    for ref in chapters:
        chapter = frappe.get_doc("Course Chapter", ref.chapter)
        drop = [r.lesson for r in chapter.lessons if is_generated(frappe, r.lesson)]
        item = built.get(chapter.title)
        have = item and frappe.db.get_value("Course Lesson", {"chapter": chapter.name, "title": item["title"],
                                                              "creation": [">=", GENERATED_SINCE]})
        print(f"{chapter.title}: remove {len(drop)}" + (f", add “{item['title']}”" if item and not have else "")
              + (f", update “{item['title']}”" if have else ""))
        if not apply or (not item and not drop):
            continue
        if have:  # a lesson this tooling built earlier: refresh its content in place
            frappe.db.set_value("Course Lesson", have, "content", item["content"])
        new = None
        if item and not have:
            new = frappe.get_doc({"doctype": "Course Lesson", "title": item["title"], "chapter": chapter.name,
                                  "course": COURSE, "content": item["content"], "include_in_preview": 0}
                                 ).insert(ignore_permissions=True).name
        chapter.reload()
        keep = [r for r in chapter.lessons if r.lesson not in drop and r.lesson != new]
        chapter.lessons = []
        if new:
            chapter.append("lessons", {"lesson": new})
        chapter.lessons.extend(keep)
        for i, row in enumerate(chapter.lessons, 1):
            row.idx = i
        chapter.save(ignore_permissions=True)
        # A learner who stopped on a removed lesson continues at the chapter's first lesson; progress rows
        # for removed lessons go with them.
        first = chapter.lessons[0].lesson if chapter.lessons else None
        for lesson in drop:
            for e in frappe.get_all("LMS Enrollment", filters={"current_lesson": lesson}, pluck="name"):
                frappe.db.set_value("LMS Enrollment", e, "current_lesson", first, update_modified=False)
            for doctype in ("LMS Course Progress", "LMS Video Watch Duration", "LMS Lesson Note"):
                for row in frappe.get_all(doctype, filters={"lesson": lesson}, pluck="name"):
                    frappe.delete_doc(doctype, row, ignore_permissions=True, force=True)
            frappe.delete_doc("Course Lesson", lesson, ignore_permissions=True)
        frappe.db.commit()
    frappe.destroy()


if __name__ == "__main__":
    main(sys.argv[1], "--apply" in sys.argv)

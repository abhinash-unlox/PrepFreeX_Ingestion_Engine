import json
import re

with open("data/reference/syllabus_extracted_text.txt", "r", encoding="utf-8") as f:
    text = f.read()

# Remove page header lines
text = re.sub(r"--- PAGE \d+ ---", "", text)
text = re.sub(r"JEE Mains Curriculum & Concept Structure", "", text)
text = re.sub(r"Official Hierarchy of Chapters and Micro-Subtopics Drill Modules.*?\n", "", text)

# Split by Subject
sections = re.split(r"(MATHEMATICS \(16 Units\)|PHYSICS \(20 Units\)|CHEMISTRY \(28 Units\))", text)

syllabus_data = {
    "subjects": []
}

current_subject = None

for sec in sections:
    sec_str = sec.strip()
    if not sec_str:
        continue
    if "MATHEMATICS" in sec_str:
        current_subject = "MATHEMATICS"
        syllabus_data["subjects"].append({"subject": "MATHEMATICS", "units": []})
        continue
    elif "PHYSICS" in sec_str:
        current_subject = "PHYSICS"
        syllabus_data["subjects"].append({"subject": "PHYSICS", "units": []})
        continue
    elif "CHEMISTRY" in sec_str:
        current_subject = "CHEMISTRY"
        syllabus_data["subjects"].append({"subject": "CHEMISTRY", "units": []})
        continue
    
    if current_subject:
        # Parse units in this section
        # Pattern: (MATH_U\d+|PHYS_U\d+|CHEM_U\d+)\s+Chapter\s+(\d+):\s+(.*?)\n1\.\s+(.*?)\n2\.\s+(.*?)\n3\.\s+(.*?)\n4\.\s+(.*?)(?=\n(?:MATH_U|PHYS_U|CHEM_U)|\Z)
        unit_blocks = re.findall(
            r"((?:MATH|PHYS|CHEM)_U\d+)\s+Chapter\s+(\d+):\s*(.*?)\n1\.\s*(.*?)\n2\.\s*(.*?)\n3\.\s*(.*?)\n4\.\s*(.*?)(?=\n(?:MATH|PHYS|CHEM)_U|\Z)",
            sec_str,
            re.S
        )
        subj_entry = [s for s in syllabus_data["subjects"] if s["subject"] == current_subject][0]
        for ub in unit_blocks:
            unit_code = ub[0].strip()
            ch_num = int(ub[1].strip())
            ch_name = re.sub(r"\s+", " ", ub[2].strip())
            t1 = re.sub(r"\s+", " ", ub[3].strip())
            t2 = re.sub(r"\s+", " ", ub[4].strip())
            t3 = re.sub(r"\s+", " ", ub[5].strip())
            t4 = re.sub(r"\s+", " ", ub[6].strip())

            topics = [
                {"topic_code": f"{unit_code}_T01", "topic_number": 1, "topic_name": t1},
                {"topic_code": f"{unit_code}_T02", "topic_number": 2, "topic_name": t2},
                {"topic_code": f"{unit_code}_T03", "topic_number": 3, "topic_name": t3},
                {"topic_code": f"{unit_code}_T04", "topic_number": 4, "topic_name": t4},
            ]

            subj_entry["units"].append({
                "unit_code": unit_code,
                "chapter_number": ch_num,
                "chapter_name": ch_name,
                "topics": topics
            })

# Verify counts
total_units = sum(len(s["units"]) for s in syllabus_data["subjects"])
total_topics = sum(sum(len(u["topics"]) for u in s["units"]) for s in syllabus_data["subjects"])
print(f"PARSED: {len(syllabus_data['subjects'])} Subjects | {total_units} Units/Chapters | {total_topics} Topics")
for s in syllabus_data["subjects"]:
    print(f" - {s['subject']}: {len(s['units'])} Units, {sum(len(u['topics']) for u in s['units'])} Topics")

with open("data/reference/official_256_topics.json", "w", encoding="utf-8") as f:
    json.dump(syllabus_data, f, indent=2)

print("Saved to data/reference/official_256_topics.json")


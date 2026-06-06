"""
import_women_in_news_2025.py
---------------------------
Imports case studies from the WAN-IFRA / Women in News report:
"The Age of AI in the Newsroom: Case studies from 8 media organisations"
Written by Lyndsey Jones, published 2025.

8 case studies covering organisations in Moldova, Azerbaijan, Ukraine,
Lebanon, Kenya, Jordan, Zimbabwe, and the Philippines.

Usage:
    python import_women_in_news_2025.py
    python import_women_in_news_2025.py --dry-run
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scraper_base import get_db, insert_use_case, log_summary

logger = logging.getLogger("women_in_news")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s")

SOURCE_NAME = "WAN-IFRA Age of AI in the Newsroom"
SOURCE_CAT  = "Curated"
SOURCE_URL  = "https://womeninnews.org/wp-content/uploads/2025/05/The-Age-of-AI-in-the-newsroom-Report_EN.pdf"
DATE_PUB    = "2025-05"

USE_CASES = [
    {
        "title":        "Diez uses ChatGPT article summaries and text-to-voice to increase readership time",
        "organisation": "Diez",
        "country":      "Moldova",
        "summary":      "News production,Audience Engagement,Generative AI",
        "raw_text":     (
            "Organisation: Diez (diez.md)\n"
            "Country: Moldova\n"
            "The Moldovan website Diez.md implemented two AI tools to improve user retention: "
            "ChatGPT for article summaries and a text-to-voice application so users could listen to articles. "
            "Despite achieving over a million monthly views, average article viewing time was 47 seconds. "
            "After implementing the tools in September 2024, viewing time increased to 52 seconds. "
            "Journalists now take about 10 minutes to write summaries using ChatGPT, down from about an hour. "
            "A minimal viable product for text-to-speech was created in Russian. "
            "Challenges included load times, summary accuracy, and journalist buy-in. "
            "The team conducted sprints, appointed a project lead, and monitored results via Google Analytics.\n"
            "Source: WAN-IFRA / Women in News: Age of AI in the Newsroom (2025), pp. 4-7"
        ),
    },
    {
        "title":        "Baku Press Club builds GenAI tool to generate social media posts in Azerbaijani",
        "organisation": "Baku Press Club",
        "country":      "Azerbaijan",
        "summary":      "News distribution,Generative AI,Audience Engagement",
        "raw_text":     (
            "Organisation: Baku Press Club\n"
            "Country: Azerbaijan\n"
            "Baku Press Club developed a generative AI tool to prepare social media posts in Azerbaijani, "
            "increasing page views by 7 per cent in five months (from 39,500 in May to 42,500 by November 2024). "
            "The tool was built using the club's archived content from 2018-2024 to limit hallucinations. "
            "It saved about half an hour per article in creating social media posts. "
            "The tool works in 35 languages including Japanese and Urdu, with potential for commercial scaling. "
            "Funded partly by the EU4IM programme. Built by two dedicated software engineers. "
            "Editors choose from prompts or write custom prompts to define style and tone.\n"
            "Source: WAN-IFRA / Women in News: Age of AI in the Newsroom (2025), pp. 8-10"
        ),
    },
    {
        "title":        "Rayon.in.ua uses AI to manage HR, onboarding and grant writing during wartime",
        "organisation": "Rayon.in.ua",
        "country":      "Ukraine",
        "summary":      "AI Strategy,Management,News production",
        "raw_text":     (
            "Organisation: Rayon.in.ua\n"
            "Country: Ukraine\n"
            "Rayon.in.ua, a national network of 63 hyperlocal Ukrainian media outlets with up to 2 million "
            "monthly users, used AI tools including ChatGPT to improve efficiency during wartime. "
            "Key applications included: GPT assistant for grant writing (directly increased revenue, saved "
            "resources on translation and brainstorming); personalised journalist training programmes; "
            "AI-powered virtual chatbot for employee onboarding; automated video transcription using Glasp "
            "and Claude to repackage video content into articles; AI editorial policy covering transparency, "
            "ethics and quality. Training sessions conducted for all 50 journalists. "
            "Found GPT good for grant applications but not for writing website articles directly.\n"
            "Source: WAN-IFRA / Women in News: Age of AI in the Newsroom (2025), pp. 11-14"
        ),
    },
    {
        "title":        "Al Araby Al Jadeed tests Arabic text-to-speech tools despite wartime disruption",
        "organisation": "Al Araby Al Jadeed",
        "country":      "Lebanon",
        "summary":      "Synthetic Media,Research & Innovation",
        "raw_text":     (
            "Organisation: Al Araby Al Jadeed (New Arab)\n"
            "Country: Lebanon\n"
            "Al Araby Al Jadeed tested text-to-speech and speech-to-text tools for Arabic content, "
            "experimenting with Play.ht, Murf.ai, Sonix, and Mastera AI. "
            "Key challenge: Arabic language AI datasets are less developed than English, leading to less "
            "accurate outputs. Team found placing diacritics on every letter improved accuracy. "
            "Project was disrupted when Israel launched its ground invasion of Lebanon in October 2024. "
            "Staff were forced to relocate but continued working. "
            "Future plans include an AI tool to scan the newspaper and generate weekly quiz questions.\n"
            "Source: WAN-IFRA / Women in News: Age of AI in the Newsroom (2025), pp. 15-18"
        ),
    },
    {
        "title":        "Radio Africa Group trials ElevenLabs text-to-speech for advertisement audio clips",
        "organisation": "Radio Africa Group",
        "country":      "Kenya",
        "summary":      "Synthetic Media,News production,Audience Engagement",
        "raw_text":     (
            "Organisation: Radio Africa Group (Kiss FM, Classic FM, Radio Jambo, Kiss TV, The Star)\n"
            "Country: Kenya\n"
            "Radio Africa Group tested ElevenLabs text-to-speech to create advertisement audio clips, "
            "targeting a 30 per cent cut in voiceover costs. The experiment was successful for advertising. "
            "Also used ChatGPT to convert articles into radio bulletins, Meltwater, Hootsuite and VideoGen. "
            "Challenges: ElevenLabs did not understand Swahili words and required phonetic spelling. "
            "Initial staff resistance due to fears of job losses was addressed by appointing three AI champions. "
            "Other tools already in use: Grammarly, ChatGPT for press releases, VideoGen. "
            "Plans to roll out ElevenLabs to editorial and transition from radio to social media explainers.\n"
            "Source: WAN-IFRA / Women in News: Age of AI in the Newsroom (2025), pp. 19-22"
        ),
    },
    {
        "title":        "Al Mamlaka develops AI news anchor 'Raeda' and face/voice recognition systems",
        "organisation": "Al Mamlaka",
        "country":      "Jordan",
        "summary":      "Synthetic Media,News production,Audience Engagement",
        "raw_text":     (
            "Organisation: Al Mamlaka TV (The Kingdom)\n"
            "Country: Jordan\n"
            "Al Mamlaka, a Jordanian TV station with 4 million Facebook followers, developed multiple AI "
            "projects including: Jordan's first female AI TV presenter called 'Raeda' (in development); "
            "AI-powered face recognition for camera crane to track presenters; voice recognition teleprompter; "
            "AI interview transcription; upgraded Avid system for script writing. "
            "Also building AI-driven content analytics, personalised recommendations and sentiment analysis. "
            "Goal: increase interaction rates by at least 15 per cent through AI anchor. "
            "Also encouraging journalists to use AI for research and scriptwriting.\n"
            "Source: WAN-IFRA / Women in News: Age of AI in the Newsroom (2025), pp. 23-27"
        ),
    },
    {
        "title":        "ZiFM Stereo plans AI workflow automation to target Zimbabwean diaspora",
        "organisation": "ZiFM Stereo",
        "country":      "Zimbabwe",
        "summary":      "News distribution,AI Strategy,News production",
        "raw_text":     (
            "Organisation: ZiFM Stereo (part of AB Communications)\n"
            "Country: Zimbabwe\n"
            "ZiFM Stereo planned to use AI tools to convert radio and news content into digital formats "
            "(summary articles, audio podcasts, video content, social media content) targeting 4 million "
            "Zimbabweans in the diaspora. Goal: 1,000 digital-only subscribers in 3 months, 10,000 in a year. "
            "Project was delayed when the managing director who supported it left the company. "
            "The team continued small-scale testing and research while waiting for leadership to stabilise. "
            "Budget requirements were relatively low, making the project potentially achievable.\n"
            "Source: WAN-IFRA / Women in News: Age of AI in the Newsroom (2025), pp. 28-31"
        ),
    },
    {
        "title":        "SunStar Cebu develops bottom-up AI editorial policy while experimenting with generative AI tools",
        "organisation": "SunStar Cebu",
        "country":      "Philippines",
        "summary":      "AI Strategy,Responsible AI,News production",
        "raw_text":     (
            "Organisation: SunStar Cebu\n"
            "Country: Philippines\n"
            "SunStar Cebu (founded 1982) encouraged journalists to experiment with generative AI tools while "
            "simultaneously developing an AI policy through a bottom-up approach. "
            "Tools tested included: text correction, headline and caption suggestions, social media blurbs, "
            "SEO keywords and meta tags. "
            "Four-point AI policy developed: (1) disclaimer on all AI-assisted content; "
            "(2) human editor must verify all AI content before publication; "
            "(3) AI not used to manipulate photos without attribution; "
            "(4) journalists must not rely on AI alone for fact-checking. "
            "Currently using disclaimer: 'This article was made with the help of an automated editorial system.'\n"
            "Source: WAN-IFRA / Women in News: Age of AI in the Newsroom (2025), pp. 30-31"
        ),
    },
]


def import_cases(dry_run: bool = False) -> None:
    conn      = get_db()
    attempted = 0
    inserted  = 0

    for case in USE_CASES:
        attempted += 1
        record = {
            "source_name":     SOURCE_NAME,
            "source_category": SOURCE_CAT,
            "source_url":      SOURCE_URL,
            "date_published":  DATE_PUB,
            "url":             SOURCE_URL,
            **case,
        }

        if dry_run:
            logger.info("DRY RUN - would insert: [%s] %s",
                        case.get("country"), case.get("title", "")[:70])
            continue

        if insert_use_case(conn, record):
            inserted += 1
            logger.info("  + [%s] %s", case.get("country"), case.get("title", "")[:70])

    if not dry_run:
        log_summary(SOURCE_NAME, attempted, inserted)
    else:
        logger.info("DRY RUN complete - %d cases would be imported", attempted)

    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Import WAN-IFRA / Women in News Age of AI report into database")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview without writing to DB")
    args = parser.parse_args()
    import_cases(dry_run=args.dry_run)

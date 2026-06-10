\
\
\
\
\
\
\
\
\
   

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scraper_base import get_db, insert_use_case, log_summary

logger = logging.getLogger("reuters_dnr")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s")

SOURCE_NAME = "Reuters Institute Digital News Report 2025"
SOURCE_CAT  = "Curated"
SOURCE_URL  = "https://www.digitalnewsreport.org/"
DATE_PUB    = "2025-06"

                                                                                 
                                                       

USE_CASES = [
    {
        "title":        "Reach uses AI tool Gutenbot to rewrite stories across its network",
        "organisation": "Reach",
        "country":      "United Kingdom",
        "summary":      "The UK's largest regional publisher Reach employs an AI tool called Gutenbot to assist journalists in rewriting stories for different websites within its network.",
        "raw_text":     "Organisation: Reach\nCountry: United Kingdom\nThe UK's largest regional publisher Reach employs an AI tool called Gutenbot to assist its journalists in rewriting stories for different websites within its network.\nSource: Reuters Institute Digital News Report 2025, p.30",
    },
    {
        "title":        "Express.de uses AI bot 'Klara Indernach' to author news stories",
        "organisation": "Express.de",
        "country":      "Germany",
        "summary":      "The German tabloid Express.de used an AI bot called 'Klara Indernach' to author more than 1,500 stories, accounting for 10% of stories read.",
        "raw_text":     "Organisation: Express.de\nCountry: Germany\nThe German tabloid Express.de has used an AI bot called 'Klara Indernach' to author more than 1,500 stories, accounting for 10% of stories read.\nSource: Reuters Institute Digital News Report 2025, p.30",
    },
    {
        "title":        "TVOne uses AI-generated reporters to present content on social media",
        "organisation": "TVOne",
        "country":      "Indonesia",
        "summary":      "The leading Indonesian broadcaster TVOne uses AI-generated reporters to present content via its social media channels.",
        "raw_text":     "Organisation: TVOne\nCountry: Indonesia\nIn Indonesia, the leading broadcaster TVOne uses AI-generated reporters to present content via its social media channels.\nSource: Reuters Institute Digital News Report 2025, p.30",
    },
    {
        "title":        "Mono 29 deploys AI anchor Nong Marisa to present TV news",
        "organisation": "Mono 29",
        "country":      "Thailand",
        "summary":      "Nong Marisa is an AI anchor in Thailand which presents the news on the Mono 29 TV channel.",
        "raw_text":     "Organisation: Mono 29\nCountry: Thailand\nNong Marisa is an AI anchor in Thailand which presents the news on the Mono 29 TV channel.\nSource: Reuters Institute Digital News Report 2025, p.30",
    },
    {
        "title":        "BBC trials OpenAI Whisper to add subtitles and transcripts to BBC Sounds",
        "organisation": "BBC",
        "country":      "United Kingdom",
        "summary":      "The BBC has been trialling OpenAI's speech-to-text tool Whisper to add subtitles and transcripts to some items published on BBC Sounds.",
        "raw_text":     "Organisation: BBC\nCountry: United Kingdom\nThe BBC has been trialling OpenAI's speech-to-text tool Whisper to add subtitles and transcripts to some items published on BBC Sounds.\nSource: Reuters Institute Digital News Report 2025, p.50",
    },
    {
        "title":        "BBC News announces AI department to deepen personalisation for younger audiences",
        "organisation": "BBC",
        "country":      "United Kingdom",
        "summary":      "BBC News CEO Deborah Turness announced plans to create a new department using AI to deepen personalisation and better tailor news content for younger audiences.",
        "raw_text":     "Organisation: BBC\nCountry: United Kingdom\nBBC News CEO Deborah Turness announced the creation of a new department that will use AI to deepen personalisation: 'We must become ruthlessly focused on understanding our audience needs, on delivering the kind of journalism and content they want, in the places they want it, designed and produced in the shape that they enjoy it.'\nSource: Reuters Institute Digital News Report 2025, p.50",
    },
    {
        "title":        "India Today and Miami Herald test AI text-to-audio conversion",
        "organisation": "India Today",
        "country":      "India",
        "summary":      "India Today and the Miami Herald have been testing AI technologies that allow users to turn text articles into audio using an AI-generated voice.",
        "raw_text":     "Organisation: India Today, Miami Herald\nCountry: India, United States\nIndia Today and the Miami Herald have been testing AI technologies that allow users to turn text articles into audio, using an AI-generated voice.\nSource: Reuters Institute Digital News Report 2025, p.50",
    },
    {
        "title":        "Miami Herald tests AI text-to-audio conversion for news articles",
        "organisation": "Miami Herald",
        "country":      "United States",
        "summary":      "The Miami Herald has been testing AI technologies that allow users to turn text articles into audio using an AI-generated voice.",
        "raw_text":     "Organisation: Miami Herald\nCountry: United States\nThe Miami Herald has been testing AI technologies that allow users to turn text articles into audio, using an AI-generated voice.\nSource: Reuters Institute Digital News Report 2025, p.50",
    },
    {
        "title":        "Aftonbladet introduces AI-produced 'quick versions' of news stories",
        "organisation": "Aftonbladet",
        "country":      "Sweden",
        "summary":      "Swedish newspaper Aftonbladet has introduced 'quick versions' of news stories produced with AI on top of extended versions of articles.",
        "raw_text":     "Organisation: Aftonbladet\nCountry: Sweden\nSwedish newspaper Aftonbladet has introduced 'quick versions' of news stories produced with AI on top of extended versions of articles.\nSource: Reuters Institute Digital News Report 2025, p.50",
    },
    {
        "title":        "Clarín offers AI-powered supplementary analyses via UalterAI",
        "organisation": "Clarín",
        "country":      "Argentina",
        "summary":      "Argentina's Clarín newspaper offers users a text-to-audio option and UalterAI, a tool offering supplementary analyses including key bullet points, highlighted quotes, key figures, a glossary, and FAQs.",
        "raw_text":     "Organisation: Clarín\nCountry: Argentina\nArgentina's Clarín newspaper now offers users both a text-to-audio option and UalterAI, a tool offering a range of supplementary analyses ranging from key bullet points and highlighted quotes, to key figures, a glossary, and a list of Frequently Asked Questions.\nSource: Reuters Institute Digital News Report 2025, p.50",
    },
    {
        "title":        "The Independent launches 'Bulletin' — AI-generated news summaries for younger readers",
        "organisation": "The Independent",
        "country":      "United Kingdom",
        "summary":      "The Independent (UK) launched a new digital news service called Bulletin — 'News for Seriously Busy People' — which uses Google's generative AI service Gemini to create article summaries overseen by journalists, aimed at younger readers.",
        "raw_text":     "Organisation: The Independent\nCountry: United Kingdom\nThe Independent (UK) has launched a new digital news service called Bulletin – advertised as 'News for Seriously Busy People' – which uses Google's generative AI service Gemini to create article summaries overseen by journalists, aimed at younger readers.\nSource: Reuters Institute Digital News Report 2025, p.50",
    },
    {
        "title":        "Washington Post launches generative AI tool to answer user questions from article archive",
        "organisation": "Washington Post",
        "country":      "United States",
        "summary":      "The Washington Post launched a generative AI tool that can answer user questions based on its own corpus of articles, functioning as an advanced search tool that understands complex queries.",
        "raw_text":     "Organisation: Washington Post\nCountry: United States\nThe Washington Post launched a generative AI tool that can answer user questions based on their own corpus of articles. Rather than modifying news story formats, the tool provides an advanced search function that can understand complex queries.\nSource: Reuters Institute Digital News Report 2025, p.50",
    },
    {
        "title":        "Financial Times launches generative AI tool to answer reader questions",
        "organisation": "Financial Times",
        "country":      "United Kingdom",
        "summary":      "The Financial Times launched a generative AI tool that can answer user questions based on its own corpus of articles, providing an advanced search function that can understand complex queries.",
        "raw_text":     "Organisation: Financial Times\nCountry: United Kingdom\nThe Financial Times launched a generative AI tool that can answer user questions based on their own corpus of articles. Rather than modifying news story formats, the tool provides an advanced search function that can understand complex queries.\nSource: Reuters Institute Digital News Report 2025, p.50",
    },
    {
        "title":        "Aftonbladet uses transparent ethics boxes to explain AI reporting processes",
        "organisation": "Aftonbladet",
        "country":      "Sweden",
        "summary":      "Swedish publication Aftonbladet uses 'transparent' ethics boxes to explain its AI reporting processes to readers.",
        "raw_text":     "Organisation: Aftonbladet\nCountry: Sweden\nSwedish publication Aftonbladet uses 'transparent' ethics boxes to explain reporting processes including AI use.\nSource: Reuters Institute Digital News Report 2025, p.~28",
    },
    {
        "title":        "Globe and Mail invests in new journalistic beats including happiness and healthy living reporters",
        "organisation": "Globe and Mail",
        "country":      "Canada",
        "summary":      "The Globe and Mail in Canada invested in new journalistic beats including a happiness reporter and a healthy living reporter as part of audience engagement strategies.",
        "raw_text":     "Organisation: Globe and Mail\nCountry: Canada\nThe Globe and Mail in Canada has invested in new journalistic beats including a happiness reporter and a healthy living reporter, as part of broader audience engagement and user-needs based approaches.\nSource: Reuters Institute Digital News Report 2025, p.29",
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
            logger.info("DRY RUN — would insert: [%s] %s",
                        case.get("country"), case.get("title", "")[:70])
            continue

        if insert_use_case(conn, record):
            inserted += 1
            logger.info("  + [%s] %s", case.get("country"), case.get("title", "")[:70])

    if not dry_run:
        log_summary(SOURCE_NAME, attempted, inserted)
    else:
        logger.info("DRY RUN complete — %d cases would be imported", attempted)

    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Import Reuters Institute DNR 2025 AI use cases into database")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview without writing to DB")
    args = parser.parse_args()
    import_cases(dry_run=args.dry_run)

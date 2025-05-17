import os
import json
import time
import logging
from typing import List, Dict, Any
from datetime import datetime

import requests
import openai

from database_models import (
    init_db, get_session, Event, Association, SearchQuery
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

from dotenv import load_dotenv
load_dotenv()

openai.api_key  = os.getenv("OPENAI_API_KEY")
SERPER_API_KEY  = os.getenv("SERPER_API_KEY")

class TedlarLeadGenerator:
    def __init__(self):
        init_db()
        self.session = get_session()

    def generate_search_queries(self, num_queries: int = 10) -> List[str]:
        logger.info(f"Generating {num_queries} search queries using AI")
        prompt = f"""
        DuPont Tedlar® produces protective PVF films used in:
        - Outdoor signage exposed to UV, weather, and graffiti
        - Vehicle wraps and fleet graphics
        - Architectural graphics and decorative panels

        Generate {num_queries} concise search phrases (3–5 words each) optimized for finding:
        • 2025 trade shows (e.g. “ISA Sign Expo 2025”)
        • Regional signage conferences
        • Relevant trade associations

        Return as a JSON object with key "queries" mapping to an array of strings.
        """
        resp = openai.chat.completions.create(
            model="gpt-4-turbo-preview",
            messages=[
                {"role": "system",  "content": "You are an expert at crafting Google-style search phrases for industry events."},
                {"role": "user",    "content": prompt}
            ],
            response_format={"type": "json_object"}
        )
        raw = resp.choices[0].message.content
        try:
            payload = json.loads(raw)
            queries = payload.get("queries", [])
            for q in queries:
                sq = SearchQuery(query_text=q, query_source="AI")
                self.session.add(sq)
            self.session.commit()
            return queries
        except Exception as e:
            logger.error("Failed to parse search-query JSON: %s", e)
            return []

    def search_web(self, query: str, num_results: int = 10) -> List[Dict[str, Any]]:
        logger.info(f"Searching web for: {query}")
        try:
            resp = requests.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
                json={"q": query, "num": num_results}
            )
            if resp.status_code != 200:
                logger.error("Search API failed (%d): %s", resp.status_code, resp.text)
                return []
            data = resp.json()
            hits = data.get("organic") or []
            sq = self.session.query(SearchQuery).filter_by(query_text=query).first()
            if sq:
                sq.results_count = len(hits)
                self.session.commit()
            return hits
        except Exception as e:
            logger.error("Error during web search: %s", e)
            return []

    def analyze_search_results(
        self, query: str, results: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        logger.info(f"Analyzing {len(results)} results for '{query}'")
        if not results:
            return []
        snippet = json.dumps(results[:5], indent=2)
        prompt = f"""
        The following are search results for "{query}" related to DuPont Tedlar® graphics & signage films:

        {snippet}

        Extract only items that are (a) trade shows or (b) trade associations. For each, output:
        1. type: "event" or "association"
        2. name: full name
        3. website: URL
        4. description: 15–25 words based on title/snippet
        5. relevance: 0.0–1.0 score
        6. dates: (events only)
        7. location: (events only)

        Return JSON object with key "items" → array of these objects.
        """
        resp = openai.chat.completions.create(
            model="gpt-4-turbo-preview",
            messages=[
                {"role": "system", "content": "You extract structured data on events and associations."},
                {"role": "user",   "content": prompt}
            ],
            response_format={"type": "json_object"}
        )
        raw = resp.choices[0].message.content
        try:
            payload = json.loads(raw)
            return payload.get("items", [])
        except Exception as e:
            logger.error("Failed to parse analysis JSON: %s", e)
            return []

    def store_relevant_items(self, items: List[Dict[str, Any]]):
        for item in items:
            t = item.get("type", "").lower()
            if t == "event":
                ev = Event(
                    name=item["name"],
                    event_type="trade show",
                    description=item.get("description", ""),
                    website=item.get("website", ""),
                    relevance_score=float(item.get("relevance", 0)),
                    notes="via AI query"
                )
                self.session.add(ev)
            elif t == "association":
                assoc = Association(
                    name=item["name"],
                    description=item.get("description", ""),
                    website=item.get("website", ""),
                    relevance_score=float(item.get("relevance", 0)),
                    notes="via AI query"
                )
                self.session.add(assoc)
        self.session.commit()

    def run_research_pipeline(self, num_queries=5, results_per_query=10, max_items=10):
        logger.info("Starting research pipeline")
        queries = self.generate_search_queries(num_queries)
        seen = set()
        all_items = []
        for q in queries:
            hits = self.search_web(q, results_per_query)
            items = self.analyze_search_results(q, hits)
            for item in items:
                name = item.get("name")
                if name and name not in seen:
                    self.store_relevant_items([item])
                    seen.add(name)
                    all_items.append(item)
                if len(seen) >= max_items:
                    break
            if len(seen) >= max_items:
                break
            time.sleep(1)
        logger.info(f"Pipeline completed. Stored {len(all_items)} unique items.")
        return {"queries_generated": len(queries), "items_found": len(all_items)}

    def get_top_events(self, limit=10):
        return self.session.query(Event).order_by(Event.relevance_score.desc()).limit(limit).all()

    def get_top_associations(self, limit=10):
        return self.session.query(Association).order_by(Association.relevance_score.desc()).limit(limit).all()

    def export_results_to_csv(self, filename="results.csv"):
        import pandas as pd
        evs = self.get_top_events(limit=100)
        assocs = self.get_top_associations(limit=100)
        rows = []
        for e in evs:
            rows.append({"type":"Event","name":e.name,"website":e.website,"score":e.relevance_score})
        for a in assocs:
            rows.append({"type":"Association","name":a.name,"website":a.website,"score":a.relevance_score})
        df = pd.DataFrame(rows)
        df.to_csv(filename, index=False)
        return filename


import os
import json
import logging
import requests
import time
from typing import List, Dict, Any

import openai
from sqlalchemy.orm import Session
from sqlalchemy import func
from database_models import get_session, Company, Person

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load API keys
from dotenv import load_dotenv
load_dotenv()

openai.api_key = os.getenv("OPENAI_API_KEY")
SERPER_API_KEY = os.getenv("SERPER_API_KEY")

class DecisionMakerFinder:
    def __init__(self):
        self.session = get_session()
    
    def find_decision_makers_for_all_companies(self, limit: int = 25):
        """Process all companies in the database to find their decision makers."""
        companies = self.session.query(Company).order_by(Company.relevance_score.desc()).limit(limit).all()
        
        total_execs = 0
        for company in companies:
            logger.info(f"Finding decision makers for {company.name}")
            executives = self.find_company_executives(company)
            self.store_executives(company, executives)
            total_execs += len(executives)
            
            # Add a small delay to avoid hitting API rate limits
            time.sleep(1)
            
        logger.info(f"Processed {total_execs} executives for {len(companies)} companies")
        return total_execs
    
    def find_company_executives(self, company: Company) -> List[Dict[str, Any]]:
        """Find executives for a given company, prioritizing signage division."""
        # First try to find signage division leadership
        signage_query = f"{company.name} signage graphics division leadership executives"
        signage_execs = self._search_executives(signage_query, company.name)
        
        if signage_execs:
            for exec_info in signage_execs:
                exec_info["division"] = "Signage/Graphics"
            return signage_execs
        
        # If no signage division found, look for general leadership
        general_query = f"{company.name} executive leadership team"
        general_execs = self._search_executives(general_query, company.name)
        
        if general_execs:
            for exec_info in general_execs:
                exec_info["division"] = "General"
        
        return general_execs or []
    
    def _search_executives(self, query: str, company_name: str) -> List[Dict[str, Any]]:
        """Search for executives using the Serper API and analyze with GPT."""
        try:
            # Search for executives using Serper
            logger.info(f"Searching for: {query}")
            resp = requests.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
                json={"q": query, "num": 5}
            )
            
            if resp.status_code != 200:
                logger.error(f"Search API failed ({resp.status_code}): {resp.text}")
                return []
            
            search_data = resp.json()
            search_results = search_data.get("organic", [])
            
            if not search_results:
                logger.warning(f"No search results found for {query}")
                return []
            
            # Fetch more detailed information from top result to get better executive data
            top_urls = [result.get("link") for result in search_results[:2] if result.get("link")]
            detailed_content = ""
            
            for url in top_urls:
                if "linkedin.com" in url:
                    # Skip LinkedIn URLs as they often require login
                    continue
                try:
                    page_resp = requests.get(url, timeout=10)
                    if page_resp.status_code == 200:
                        detailed_content += f"\nContent from {url}:\n"
                        detailed_content += page_resp.text[:10000]  # Limit content size
                except Exception as e:
                    logger.warning(f"Failed to fetch {url}: {e}")
            
            # Format the search results for AI analysis
            search_content = json.dumps(search_results[:3], indent=2)
            
            # Use OpenAI to extract executive information
            prompt = f"""
            The following are search results about executives at {company_name}:
            
            {search_content}
            
            Additional website content:
            {detailed_content[:5000] if detailed_content else "No additional content"}
            
            Extract executives/decision makers from these results. For each person, provide:
            1. name: Full name
            2. title: Job title (focus on leadership positions related to graphics, signage, marketing, or sales)
            3. linkedin: LinkedIn URL (if available)
            4. email: Email address (if available)
            5. relevance_score: 0.0-1.0 score indicating how relevant they are for signage/graphics-related decisions
               - 0.9-1.0: Direct leadership of signage/graphics division
               - 0.7-0.8: Marketing/sales leadership who might influence signage decisions
               - 0.4-0.6: General executives with possible influence
               - 0.1-0.3: Executives unlikely to be involved in signage decisions
            
            Only include people who are actually executives at {company_name}. If the search results don't contain executive information, return an empty array.
            
            Return as a JSON object with key "executives" mapping to an array of these person objects.
            """
            
            resp = openai.chat.completions.create(
                model="gpt-4-turbo-preview",
                messages=[
                    {"role": "system", "content": "You extract structured data about company executives."},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"}
            )
            
            raw = resp.choices[0].message.content
            try:
                payload = json.loads(raw)
                execs = payload.get("executives", [])
                logger.info(f"Found {len(execs)} executives for {company_name}")
                return execs
            except Exception as e:
                logger.error(f"Failed to parse executive JSON: {e}")
                return []
                
        except Exception as e:
            logger.error(f"Error during executive search: {e}")
            return []
    
    def store_executives(self, company: Company, executives: List[Dict[str, Any]]):
        """Store the found executives in the database."""
        for exec_data in executives:
            # Skip if missing name or title
            if not exec_data.get("name") or not exec_data.get("title"):
                continue
                
            # Check if this executive already exists
            existing = self.session.query(Person).filter(
                Person.name == exec_data.get("name"),
                Person.company_id == company.company_id
            ).first()
            
            if existing:
                # Update existing record
                existing.title = exec_data.get("title", existing.title)
                existing.linkedin = exec_data.get("linkedin", existing.linkedin)
                existing.email = exec_data.get("email", existing.email)
                existing.division = exec_data.get("division", existing.division)
                existing.relevance_score = exec_data.get("relevance_score", existing.relevance_score)
                existing.last_updated = func.now()
                logger.info(f"Updated executive: {existing.name}")
            else:
                # Create new record
                new_exec = Person(
                    name=exec_data.get("name"),
                    title=exec_data.get("title"),
                    linkedin=exec_data.get("linkedin"),
                    email=exec_data.get("email"),
                    division=exec_data.get("division"),
                    relevance_score=float(exec_data.get("relevance_score", 0.0)),
                    company_id=company.company_id,
                    notes=f"Found via automated search"
                )
                self.session.add(new_exec)
                logger.info(f"Added new executive: {new_exec.name}")
        
        # Commit all changes
        self.session.commit()
    
    def export_executives_to_csv(self, filename="executives.csv"):
        """Export executives to a CSV file."""
        import pandas as pd
        
        # Get all executives with company names
        query = self.session.query(
            Person, Company.name.label("company_name")
        ).join(Company).all()
        
        if not query:
            logger.warning("No executives found to export")
            return None
            
        rows = []
        for person, company_name in query:
            rows.append({
                "company": company_name,
                "name": person.name,
                "title": person.title,
                "division": person.division,
                "email": person.email,
                "linkedin": person.linkedin,
                "relevance_score": person.relevance_score
            })
        
        df = pd.DataFrame(rows)
        df.to_csv(filename, index=False)
        logger.info(f"Exported {len(rows)} executives to {filename}")
        return filename

# For command-line execution
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Find decision makers for companies")
    parser.add_argument(
        "-l", "--limit", type=int, default=25,
        help="Maximum number of companies to process"
    )
    parser.add_argument(
        "-o", "--output", default="executives.csv",
        help="Output CSV file for executives"
    )
    args = parser.parse_args()
    
    finder = DecisionMakerFinder()
    finder.find_decision_makers_for_all_companies(limit=args.limit)
    finder.export_executives_to_csv(filename=args.output)
    
import os
import json
import logging
import requests
import time
import re
from typing import List, Dict, Any, Optional

import openai
import pandas as pd
from sqlalchemy.orm import Session
from database_models import get_session, Company, CompanyEvent, Event

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# Load OpenAI API key
oai_key = os.getenv("OPENAI_API_KEY")
if not oai_key:
    raise ValueError("OPENAI_API_KEY environment variable not set")
openai.api_key = oai_key

# Serper API key for company discovery
SERPER_KEY = os.getenv("SERPER_API_KEY")
if not SERPER_KEY:
    raise ValueError("SERPER_API_KEY environment variable not set")

# Wikipedia API endpoint
WIKI_API = "https://en.wikipedia.org/w/api.php"

# Keywords to identify non-company entities
EVENT_KEYWORDS = [
    "conference", "expo", "exhibition", "show", "summit", 
    "symposium", "convention", "fair", "forum", "congress",
    "2023", "2024", "2025", "2026"
]

ASSOCIATION_KEYWORDS = [
    "association", "society", "institute", "committee", "council", 
    "federation", "organization", "alliance", "coalition", "guild"
]

# ---------------------------------------------------
# Step 1: Discover companies via Serper API
# ---------------------------------------------------
def find_companies_for_event(event_name: str, limit: int = 25) -> List[str]:
    """
    Use Serper API to search related queries and extract up to `limit` unique company names.
    Filters out entries that appear to be events, conferences, or associations.
    """
    queries = [
        f"{event_name} exhibitors",
        f"{event_name} attendees",
        f"{event_name} sponsors",
        f"{event_name} companies attending"
    ]
    headers = {"X-API-KEY": SERPER_KEY, "Content-Type": "application/json"}
    company_set = []
    seen = set()
    
    for q in queries:
        if len(company_set) >= limit:
            break
        logger.info("Serper search: %s", q)
        try:
            resp = requests.post(
                "https://google.serper.dev/search",
                headers=headers,
                json={"q": q, "num": limit}
            )
            if resp.status_code != 200:
                logger.error("Serper failed for '%s': %s", q, resp.text)
                continue
                
            data = resp.json()
            hits = data.get("organic", [])
            
            for hit in hits:
                title = hit.get("title", "").strip()
                
                # Skip if empty title
                if not title:
                    continue
                    
                # Skip if already seen
                if title in seen:
                    continue
                
                seen.add(title)
                company_set.append(title)
                
                if len(company_set) >= limit:
                    break
                    
        except Exception as e:
            logger.error(f"Error searching for '{q}': {e}")
            
    logger.info("Discovered %d potential companies via Serper (limit %d)", len(company_set), limit)
    
    # Use OpenAI to filter out non-companies
    validated_companies = validate_company_names(company_set)
    
    logger.info("Validated %d actual companies (removed %d non-companies)", 
               len(validated_companies), len(company_set) - len(validated_companies))
    
    return validated_companies

def validate_company_names(company_names: List[str]) -> List[str]:
    """
    Use OpenAI to filter out entities that aren't actually companies.
    
    Args:
        company_names: List of potential company names to validate
        
    Returns:
        List of validated actual company names
    """
    if not company_names:
        return []
        
    try:
        prompt = f"""
        Below is a list of potential company names extracted from search results:
        {json.dumps(company_names)}
        
        Many items in this list might not be actual companies. They could be:
        - Events or conferences (e.g., "ISA Sign Expo 2025")
        - Trade associations (e.g., "International Sign Association")
        - Generic industry terms
        - Product names
        
        Please identify which items are ACTUAL COMPANIES (like 3M, Avery Dennison, etc.).
        
        Return your answer as a JSON object with a key "companies" containing an array of 
        strings, with only the items that are actual company names.
        """
        
        response = openai.chat.completions.create(
            model="gpt-4-turbo-preview",
            messages=[
                {"role": "system", "content": "You are a system that accurately identifies real company names."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.2  # Lower temperature for more consistent results
        )
        
        result = json.loads(response.choices[0].message.content)
        validated_companies = result.get("companies", [])
        
        # Log what was removed
        removed = set(company_names) - set(validated_companies)
        if removed:
            logger.info(f"AI removed non-companies: {', '.join(removed)}")
            
        return validated_companies
        
    except Exception as e:
        logger.error(f"Error validating company names with AI: {e}")
        # Fall back to keyword-based filtering
        return [name for name in company_names 
                if not any(keyword in name.lower() for keyword in EVENT_KEYWORDS + ASSOCIATION_KEYWORDS)]

# ---------------------------------------------------
# Step 2: Enrichment via Wikipedia
# ---------------------------------------------------
def enrich_with_wikipedia(companies: List[str]) -> List[Dict[str, Any]]:
    """
    For each company, fetch Wikipedia page to extract revenue, employees, description.
    """
    enriched = []
    for name in companies:
        try:
            r = requests.get(WIKI_API, params={
                "action": "query", "list": "search",
                "srsearch": name, "format": "json", "utf8": 1
            }).json()
            hits = r.get("query", {}).get("search", [])
            if not hits:
                raise ValueError(f"Wikipedia page not found for {name}")
            title = hits[0]["title"]
            r2 = requests.get(WIKI_API, params={
                "action": "query", "prop": "revisions",
                "rvprop": "content", "rvsection": 0,
                "titles": title, "format": "json", "utf8": 1
            }).json()
            pages = r2.get("query", {}).get("pages", {})
            wikitext = next(iter(pages.values())).get("revisions", [{}])[0].get("*", "")
            if not wikitext:
                raise ValueError(f"No content found for {title}")
                
            # Extract revenue with improved regex
            rev_m = re.search(r"\| *revenue *=[ $]*([0-9,\.]+)", wikitext)
            
            # Extract employees with improved regex
            emp_m = re.search(r"\| *num_employees *=[ ]*([0-9,]+)", wikitext)
            if not emp_m:
                emp_m = re.search(r"\| *employees *=[ ]*([0-9,]+)", wikitext)
                
            # Extract industry
            ind_m = re.search(r"\| *industry *=[ ]*(.+?)(?:\n|\|)", wikitext)
            industry = None
            if ind_m:
                industry = ind_m.group(1).strip()
                industry = re.sub(r"\[\[([^|]+\|)?([^\]]+)\]\]", r"\2", industry)
                industry = re.sub(r"\{\{.*?\}\}", "", industry)
                
            # Extract description
            parts = re.split(r"\n\n+", wikitext)
            desc = None
            if len(parts) > 1:
                desc = re.sub(r"\{\{.*?\}\}", "", parts[1]).strip()
                desc = re.sub(r"\[\[([^|]+\|)?([^\]]+)\]\]", r"\2", desc)  # Handle [[wiki|links]]
                
            enriched.append({
                "name": name,
                "revenue": rev_m.group(1).replace(",", "") if rev_m else None,
                "employees": emp_m.group(1).replace(",", "") if emp_m else None,
                "description": desc,
                "industry": industry
            })
            logger.info("Wiki enriched %s", name)
        except Exception as e:
            logger.warning("Wiki enrichment failed for %s: %s", name, e)
            enriched.append({
                "name": name, 
                "revenue": None, 
                "employees": None, 
                "description": None,
                "industry": None
            })
        time.sleep(1)  # Be kind to Wikipedia's API
    return enriched

# ---------------------------------------------------
# Step 3: Validation and Relevance Scoring via OpenAI
# ---------------------------------------------------
def validate_companies_with_openai(companies: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Use OpenAI to verify, correct data, and calculate relevance scores.
    """
    validated = []
    for comp in companies:
        prompt = f"""
I have the following data for {comp['name']}, a potential lead for DuPont Tedlar's protective PVF films for signage, graphics, and architecture:

- Industry: {comp.get('industry') or 'Unknown'}
- Revenue: {comp.get('revenue')}
- Employees: {comp.get('employees')}
- Description: {comp.get('description') or 'No description available'}

Please do these two tasks:
1. Verify these fields. If missing or obviously incorrect, correct it based on your knowledge.
2. Calculate a relevance score (0.0-1.0) for this company as a potential customer for DuPont Tedlar's protective PVF films used in:
   - Outdoor signage (weather resistance, UV protection)
   - Architectural panels
   - Vehicle wraps and fleet graphics
   - Applications requiring durability and graffiti resistance

Return a JSON object with these keys: 
- name: string
- industry: string
- revenue: string or number
- employees: string or number
- description: string
- relevance_score: number between 0.0 and 1.0
- relevance_explanation: string explaining the relevance score
"""
        try:
            resp = openai.chat.completions.create(
                model="gpt-4-turbo-preview",
                messages=[
                    {"role": "system", "content": "You are a fact-checker and lead qualification expert for industrial B2B sales."},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"}
            )
            rec = json.loads(resp.choices[0].message.content)
            validated.append(rec)
            logger.info(f"Validated & scored {comp['name']} via OpenAI (relevance: {rec.get('relevance_score', 'N/A')})")
        except Exception as e:
            logger.error(f"OpenAI validation failed for {comp['name']}: {e}")
            comp["relevance_score"] = 0.5
            comp["relevance_explanation"] = "Automatically assigned due to API error"
            validated.append(comp)
        time.sleep(0.5)
    return validated

# ---------------------------------------------------
# Step 4: Store into DB
# ---------------------------------------------------
def store_companies(session: Session, event: Event, companies_data: List[Dict[str, Any]]):
    """Store companies and their relationships to events in the database."""
    for c in companies_data:
        name = c.get("name")
        if not name:
            logger.warning("Skipping company with no name")
            continue
            
        # Format data for storage
        industry = c.get("industry")
        revenue = c.get("revenue")
        employees = c.get("employees")
        description = c.get("description") or ""
        relevance_score = c.get("relevance_score")
        relevance_explanation = c.get("relevance_explanation")
        
        # Convert to proper format for database
        if isinstance(revenue, (int, float)):
            revenue = f"${revenue:,}"
        if isinstance(employees, (int, float)):
            employees = f"{int(employees):,}"
            
        # Try to convert relevance score to float
        try:
            relevance_score = float(relevance_score) if relevance_score is not None else 0.5
        except (ValueError, TypeError):
            relevance_score = 0.5
            
        # Add notes if available
        notes = f"From event: {event.name}"
        if relevance_explanation:
            notes += f"\n\nRelevance analysis: {relevance_explanation}"
            
        # Check if company already exists
        existing = session.query(Company).filter_by(name=name).first()
        
        if not existing:
            # Create new company
            existing = Company(
                name=name,
                industry=industry,
                description=description,
                estimated_revenue=revenue,
                company_size=employees,
                relevance_score=relevance_score,
                notes=notes
            )
            session.add(existing)
            session.commit()
            logger.info(f"Created new company: {name} (relevance: {relevance_score})")
        else:
            # Update existing company if new data is better
            if not existing.industry and industry:
                existing.industry = industry
            if not existing.description and description:
                existing.description = description
            if not existing.estimated_revenue and revenue:
                existing.estimated_revenue = revenue
            if not existing.company_size and employees:
                existing.company_size = employees
                
            # Always update relevance score if it exists and is higher
            if relevance_score and (existing.relevance_score is None or relevance_score > existing.relevance_score):
                existing.relevance_score = relevance_score
                
            # Append to notes
            if existing.notes:
                existing.notes += f"\n\n{notes}"
            else:
                existing.notes = notes
                
            session.commit()
            logger.info(f"Updated existing company: {name} (relevance: {relevance_score})")
            
        # Create company-event relationship if it doesn't exist
        existing_relation = session.query(CompanyEvent).filter_by(
            company_id=existing.company_id, 
            event_id=event.event_id
        ).first()
        
        if not existing_relation:
            session.add(CompanyEvent(company_id=existing.company_id, event_id=event.event_id))
            session.commit()
            logger.info(f"Associated company {name} with event {event.name}")

# ---------------------------------------------------
# Step 5: Prioritization
# ---------------------------------------------------
def prioritize_companies(session: Session, top_n: int = 20) -> pd.DataFrame:
    """Prioritize companies based on relevance score and revenue."""
    companies = session.query(Company).all()
    rows = []
    
    for c in companies:
        # Extract revenue as numeric value for sorting
        try:
            revenue_str = c.estimated_revenue or "0"
            revenue_str = revenue_str.replace("$", "").replace(",", "")
            revenue = float(revenue_str)
        except (ValueError, AttributeError):
            revenue = 0.0
            
        # Extract employee count
        try:
            employees_str = c.company_size or "0"
            employees_str = employees_str.replace(",", "")
            employees = int(employees_str)
        except (ValueError, AttributeError):
            employees = 0
            
        # Use actual relevance score
        relevance = c.relevance_score or 0.0
        
        rows.append({
            "name": c.name,
            "industry": c.industry,
            "revenue": revenue,
            "employees": employees,
            "description": c.description,
            "relevance_score": relevance,
            "company_id": c.company_id
        })
    
    if not rows:
        logger.warning("No companies to prioritize")
        return pd.DataFrame(columns=["name", "industry", "revenue", "employees", "description", "relevance_score", "company_id"])
    
    # Create DataFrame and sort by relevance first, then by revenue
    df = pd.DataFrame(rows)
    df = df.sort_values(by=["relevance_score", "revenue"], ascending=[False, False])
    
    # Format for display
    df["revenue_display"] = df["revenue"].apply(lambda x: f"${x:,.0f}" if x > 0 else "Unknown")
    df["employees_display"] = df["employees"].apply(lambda x: f"{x:,}" if x > 0 else "Unknown")
    
    return df.head(top_n)

# ---------------------------------------------------
# Step 6: Update Existing Company Relevance Scores
# ---------------------------------------------------
def update_company_relevance_scores(session: Session, batch_size: int = 10):
    """Update relevance scores for existing companies using OpenAI."""
    companies = session.query(Company).all()
    logger.info(f"Found {len(companies)} companies to evaluate")
    
    # Process in batches to manage API usage
    for i in range(0, len(companies), batch_size):
        batch = companies[i:i+batch_size]
        logger.info(f"Processing batch {i//batch_size + 1}/{(len(companies)-1)//batch_size + 1}")
        
        for company in batch:
            try:
                # Prepare context for evaluation
                prompt = f"""
Company: {company.name}
Industry: {company.industry or 'Unknown'}
Revenue: {company.estimated_revenue or 'Unknown'}
Size: {company.company_size or 'Unknown'} employees
Description: {company.description or 'No description available'}

Evaluate this company's relevance (0.0-1.0) as a potential customer for DuPont Tedlar® protective PVF films.
DuPont Tedlar® films are used in:
- Outdoor signage and displays (weather resistance, UV protection)
- Architectural graphics and panels
- Vehicle wraps and fleet graphics
- Applications requiring durability and graffiti resistance

Return a JSON object with:
1. relevance_score (0.0-1.0)
2. relevance_explanation (brief analysis)
"""
                
                resp = openai.chat.completions.create(
                    model="gpt-4-turbo-preview",
                    messages=[
                        {"role": "system", "content": "You are an expert in evaluating B2B sales leads."},
                        {"role": "user", "content": prompt}
                    ],
                    response_format={"type": "json_object"}
                )
                
                result = json.loads(resp.choices[0].message.content)
                
                # Update company in database
                if 'relevance_score' in result:
                    old_score = company.relevance_score or 0.0
                    new_score = float(result['relevance_score'])
                    company.relevance_score = new_score
                    
                    if result.get('relevance_explanation'):
                        if company.notes:
                            company.notes += f"\n\nRelevance Analysis: {result['relevance_explanation']}"
                        else:
                            company.notes = f"Relevance Analysis: {result['relevance_explanation']}"
                    
                    session.commit()
                    logger.info(f"Updated {company.name} relevance score: {old_score:.2f} → {new_score:.2f}")
                
            except Exception as e:
                logger.error(f"Failed to update relevance for {company.name}: {e}")
            
            time.sleep(0.5)  # Rate limiting
        
    logger.info("Completed relevance score updates")
    return True


# Simple command-line interface
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Company discovery and prioritization")
    parser.add_argument("--update-relevance", action="store_true", help="Update relevance scores for existing companies")
    parser.add_argument("--event", type=str, help="Name of event to search for companies")
    parser.add_argument("--limit", type=int, default=10, help="Number of companies to find per event")
    parser.add_argument("--top", type=int, default=20, help="Number of top companies to display")
    
    args = parser.parse_args()
    
    session = get_session()
    
    if args.update_relevance:
        update_company_relevance_scores(session)
    
    if args.event:
        # Find the event in the database
        event = session.query(Event).filter(Event.name.like(f"%{args.event}%")).first()
        if not event:
            print(f"Event '{args.event}' not found in database")
            exit(1)
            
        print(f"Processing companies for event: {event.name}")
        
        # Find companies
        companies = find_companies_for_event(event.name, limit=args.limit)
        print(f"Found {len(companies)} companies")
        
        # Enrich and validate
        if companies:
            enriched = enrich_with_wikipedia(companies)
            validated = validate_companies_with_openai(enriched)
            store_companies(session, event, validated)
    
    # Get prioritized companies
    companies_df = prioritize_companies(session, top_n=args.top)
    
    # Print results
    print(f"\nTop {len(companies_df)} Companies by Relevance:")
    display_df = companies_df[["name", "industry", "revenue_display", "employees_display", "relevance_score"]]
    print(display_df.to_string(index=False))
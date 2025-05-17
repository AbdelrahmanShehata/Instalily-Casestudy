import argparse
import logging
import sys
import os
from datetime import datetime
from sqlalchemy.orm import Session

from lead_generator import TedlarLeadGenerator
from company_prioritization import (
    find_companies_for_event,
    enrich_with_wikipedia,
    validate_companies_with_openai,
    store_companies,
    prioritize_companies,
    update_company_relevance_scores,
    get_session
)
from decision_maker import DecisionMakerFinder
from messaging import LinkedInMessenger

# ─── Logging Setup ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    stream=sys.stdout
)
logger = logging.getLogger(__name__)


def main(
    num_queries: int,
    results_per_query: int,
    leads_csv: str,
    companies_csv: str,
    executives_csv: str,
    messages_csv: str,
    min_relevance: float = 0.5,
    update_relevance: bool = False,
    skip_leads: bool = False,
    skip_companies: bool = False,
    skip_executives: bool = False,
    skip_messages: bool = False
):
    """
    Main pipeline function that orchestrates the entire lead generation process.
    
    Args:
        num_queries: Number of AI-generated search queries
        results_per_query: Number of web search results per query
        leads_csv: Output file for leads (events/associations)
        companies_csv: Output file for companies
        executives_csv: Output file for executives
        messages_csv: Output file for LinkedIn messages
        min_relevance: Minimum relevance score for messaging executives
        update_relevance: Whether to update relevance scores for existing companies
        skip_leads: Skip the lead generation step
        skip_companies: Skip the company discovery step
        skip_executives: Skip the executive discovery step
        skip_messages: Skip the message generation step
    """
    session: Session = get_session()
    
    # Create output directory if needed
    os.makedirs(os.path.dirname(leads_csv) if os.path.dirname(leads_csv) else '.', exist_ok=True)
    
    # --- Step 1: Generate & store events/associations/leads ---
    if not skip_leads:
        logger.info("Starting lead generation step...")
        gen = TedlarLeadGenerator()
        summary = gen.run_research_pipeline(
            num_queries=num_queries,
            results_per_query=results_per_query
        )
        logger.info(
            "Lead pipeline done: %d queries → %d items",
            summary["queries_generated"],
            summary.get("items_found", 0)
        )

        # Export leads to CSV
        leads_path = gen.export_results_to_csv(leads_csv)
        logger.info("Leads exported to %s", leads_path)
    else:
        logger.info("Skipping lead generation step...")
        gen = TedlarLeadGenerator()

    # --- Step 2: Company sourcing, enrichment, and storage ---
    if not skip_companies:
        logger.info("Starting company discovery step...")
        
        # Fetch top events and associations
        event_list = gen.get_top_events(limit=50)  # fetch more to dedupe
        assoc_list = gen.get_top_associations(limit=50)
        
        # Combine and limit to first 10 unique
        seen_entities = set()
        entities = []
        
        # Add events
        for e in event_list:
            if e.name not in seen_entities and len(entities) < 10:
                entities.append(("Event", e))
                seen_entities.add(e.name)
                
        # Add associations
        for a in assoc_list:
            if a.name not in seen_entities and len(entities) < 10:
                entities.append(("Association", a))
                seen_entities.add(a.name)

        logger.info("Processing %d unique entities for company sourcing", len(entities))

        # Global company set to enforce 25 unique companies
        discovered_companies = set()

        for entity_type, ent in entities:
            if len(discovered_companies) >= 25:
                break
            logger.info("Sourcing companies for %s: %s", entity_type, ent.name)

            # Identify companies via Serper
            candidates = find_companies_for_event(ent.name, limit=50)
            
            # Deduplicate and take until we have 25 total
            new_companies = []
            for name in candidates:
                if name not in discovered_companies:
                    discovered_companies.add(name)
                    new_companies.append(name)
                if len(discovered_companies) >= 25:
                    break
            logger.info("  → Found %d new companies (total %d)", len(new_companies), len(discovered_companies))

            if not new_companies:
                continue

            # Enrich via Wikipedia
            enriched = enrich_with_wikipedia(new_companies)
            logger.info("  → Enriched %d records via Wikipedia", len(enriched))
            
            # Validate and calculate relevance with OpenAI
            validated = validate_companies_with_openai(enriched)
            logger.info("  → Validated %d records via OpenAI", len(validated))

            # Store into DB
            store_companies(session, ent, validated)
            logger.info("  → Stored companies for %s: %s", entity_type, ent.name)
    else:
        logger.info("Skipping company discovery step...")
    
    # --- Optional: Update relevance scores for existing companies ---
    if update_relevance:
        logger.info("Updating relevance scores for all companies...")
        update_company_relevance_scores(session)
        logger.info("Relevance scores updated.")

    # --- Step 3: Prioritize companies and export ---
    df_companies = prioritize_companies(session, top_n=25)
    df_companies.to_csv(companies_csv, index=False)
    logger.info("Prioritized companies exported to %s", companies_csv)
    
    # --- Step 4: Find decision makers for companies ---
    if not skip_executives:
        logger.info("Finding decision makers for prioritized companies...")
        finder = DecisionMakerFinder()
        exec_count = finder.find_decision_makers_for_all_companies(limit=25)
        logger.info(f"Found {exec_count} executives across all companies")
        
        if exec_count > 0:
            executives_path = finder.export_executives_to_csv(filename=executives_csv)
            logger.info(f"Executives exported to {executives_path}")
        else:
            logger.warning("No executives found to export")
    else:
        logger.info("Skipping executive discovery step...")
    
    # --- Step 5: Generate LinkedIn messages for executives ---
    if not skip_messages:
        logger.info("Generating LinkedIn messages for executives...")
        messenger = LinkedInMessenger()
        message_count = messenger.generate_messages_for_all_executives(min_relevance=min_relevance)
        
        if message_count > 0:
            messages_path = messenger.export_messages_to_csv(filename=messages_csv)
            logger.info(f"Generated {message_count} LinkedIn messages, exported to {messages_path}")
        else:
            logger.warning("No LinkedIn messages generated")
    else:
        logger.info("Skipping message generation step...")
        
    logger.info("Pipeline execution completed successfully!")
    
    # Return summary of results
    return {
        "companies_count": len(df_companies),
        "companies_file": companies_csv,
        "executives_file": executives_csv if not skip_executives else None,
        "messages_file": messages_csv if not skip_messages else None
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="DuPont Tedlar lead generation and qualification pipeline"
    )
    parser.add_argument(
        "-q", "--queries", type=int, default=5,
        help="Number of AI-generated search queries"
    )
    parser.add_argument(
        "-r", "--results", type=int, default=10,
        help="Number of web search results per query"
    )
    parser.add_argument(
        "-o", "--output-dir", default="./output",
        help="Directory for output files"
    )
    parser.add_argument(
        "-rel", "--relevance", type=float, default=0.5,
        help="Minimum relevance score (0.0-1.0) for executives to message"
    )
    parser.add_argument(
        "--update-relevance", action="store_true",
        help="Update relevance scores for existing companies"
    )
    
    # Skip flags
    parser.add_argument("--skip-leads", action="store_true", help="Skip lead generation step")
    parser.add_argument("--skip-companies", action="store_true", help="Skip company discovery step")
    parser.add_argument("--skip-executives", action="store_true", help="Skip executive discovery step")
    parser.add_argument("--skip-messages", action="store_true", help="Skip message generation step")
    
    args = parser.parse_args()
    
    # Generate timestamp for file names
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    
    # Create output directory
    os.makedirs(args.output_dir, exist_ok=True)
    
    # Generate output file paths
    leads_csv = os.path.join(args.output_dir, f"tedlar_leads_{timestamp}.csv")
    companies_csv = os.path.join(args.output_dir, f"tedlar_companies_{timestamp}.csv")
    executives_csv = os.path.join(args.output_dir, f"tedlar_executives_{timestamp}.csv")
    messages_csv = os.path.join(args.output_dir, f"tedlar_messages_{timestamp}.csv")

    # Run the pipeline
    results = main(
        num_queries=args.queries,
        results_per_query=args.results,
        leads_csv=leads_csv,
        companies_csv=companies_csv,
        executives_csv=executives_csv,
        messages_csv=messages_csv,
        min_relevance=args.relevance,
        update_relevance=args.update_relevance,
        skip_leads=args.skip_leads,
        skip_companies=args.skip_companies,
        skip_executives=args.skip_executives,
        skip_messages=args.skip_messages
    )
    
    # Print summary
    print("\n=== PIPELINE EXECUTION SUMMARY ===")
    print(f"Identified and prioritized {results['companies_count']} companies")
    print(f"Companies exported to {results['companies_file']}")
    
    if results.get('executives_file'):
        print(f"Executives exported to {results['executives_file']}")
    
    if results.get('messages_file'):
        print(f"LinkedIn messages exported to {results['messages_file']}")
        
    print("\nTo view these results in the dashboard, run:")
    print("python app.py")
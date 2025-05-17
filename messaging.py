import os
import json
import time
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime

import openai
import pandas as pd
from sqlalchemy import func
from database_models import get_session, Company, Person, Message

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load OpenAI API key from environment variables
from dotenv import load_dotenv
load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

class LinkedInMessenger:
    def __init__(self):
        """Initialize the LinkedIn messenger with database connection."""
        self.session = get_session()
        
    def generate_messages_for_all_executives(self, min_relevance: float = 0.5):
        """
        Generate messages for all executives in the database with relevance score above threshold.
        
        Args:
            min_relevance: Minimum relevance score (0.0-1.0) for executives to message
        
        Returns:
            int: Number of messages generated
        """
        # Get all executives with their company info above the relevance threshold
        query = self.session.query(
            Person, Company
        ).join(
            Company, Person.company_id == Company.company_id
        ).filter(
            Person.relevance_score >= min_relevance
        ).order_by(
            Person.relevance_score.desc()
        ).all()
        
        count = 0
        for person, company in query:
            # Skip if they already have a LinkedIn connection message
            existing = self.session.query(Message).filter(
                Message.person_id == person.person_id,
                Message.message_type == 'linkedin_connect'
            ).first()
            
            if existing:
                logger.info(f"Skipping message generation for {person.name} - already exists")
                continue
                
            # Generate a personalized message
            message = self.generate_linkedin_message(person, company)
            if message:
                # Store the message
                self.store_message(person.person_id, message, 'linkedin_connect')
                count += 1
                
            # Add a small delay to avoid hitting API rate limits
            time.sleep(0.5)
            
        logger.info(f"Generated {count} LinkedIn messages")
        return count
        
    def generate_linkedin_message(self, person: Person, company: Company) -> Optional[str]:
        """
        Generate a personalized LinkedIn connection message for an executive.
        
        Args:
            person: Person object from database
            company: Company object from database
            
        Returns:
            str: Generated message or None if generation failed
        """
        try:
            # Use OpenAI to generate a personalized connection message
            prompt = self._build_message_prompt(person, company)
            
            response = openai.chat.completions.create(
                model="gpt-4-turbo-preview",
                messages=[
                    {"role": "system", "content": "You are an expert at writing personalized, concise LinkedIn connection requests."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=300,
                temperature=0.7
            )
            
            message = response.choices[0].message.content.strip()
            logger.info(f"Generated message for {person.name}")
            return message
            
        except Exception as e:
            logger.error(f"Error generating message for {person.name}: {e}")
            return None
            
    def _build_message_prompt(self, person: Person, company: Company) -> str:
        """Build the prompt for message generation based on person and company data."""
        division_focus = ""
        if person.division and person.division.lower() == "signage/graphics":
            division_focus = "specifically focusing on their signage/graphics division"
            
        return f"""
        Write a brief, personalized LinkedIn connection request message from a DuPont Tedlar® representative to {person.name}, who is {person.title} at {company.name} {division_focus}.

        The message should:
        1. Be under 300 characters (LinkedIn limit)
        2. Mention DuPont Tedlar® protective PVF films for signage/graphics applications
        3. Personalize to their role ({person.title}) and company ({company.name})
        4. Briefly mention a relevant benefit (durability, weather resistance, anti-graffiti, etc.)
        5. Have a clear, non-pushy call to action (connecting to discuss solutions)
        6. NOT include "Hi", "Hello", or any greeting (LinkedIn adds it automatically)
        
        About DuPont Tedlar®:
        - Produces protective PVF films for outdoor signage that protect against UV, weather, and graffiti
        - Used in vehicle wraps, fleet graphics, architectural panels, and outdoor displays
        - Value propositions: 20+ year durability, superior weathering, easy-clean surface
        
        Company information:
        {company.description or ""}
        
        Write ONLY the message text without any explanations.
        """
            
    def store_message(self, person_id: int, content: str, message_type: str = 'linkedin_connect'):
        """Store a generated message in the database."""
        message = Message(
            person_id=person_id,
            message_type=message_type,
            content=content,
            status='draft',
            created_date=datetime.now(),
            notes="Generated via AI"
        )
        
        self.session.add(message)
        self.session.commit()
        return message
        
    def export_messages_to_csv(self, filename: str = "linkedin_messages.csv"):
        """Export all LinkedIn messages to a CSV file."""
        # Query all messages with person and company information
        # Use explicit join paths to avoid ambiguity
        query = self.session.query(
            Message, Person, Company
        ).select_from(Message).join(
            Person, Message.person_id == Person.person_id
        ).join(
            Company, Person.company_id == Company.company_id
        ).filter(
            Message.message_type == 'linkedin_connect'
        ).all()
        
        if not query:
            logger.warning("No messages to export")
            return None
            
        # Prepare data for export
        rows = []
        for message, person, company in query:
            rows.append({
                "company": company.name,
                "person_name": person.name,
                "person_title": person.title,
                "division": person.division or "General",
                "email": person.email or "",
                "linkedin": person.linkedin or "",
                "message": message.content,
                "status": message.status,
                "created_date": message.created_date,
                "relevance_score": person.relevance_score or 0.0
            })
            
        # Export to CSV
        df = pd.DataFrame(rows)
        df.to_csv(filename, index=False)
        logger.info(f"Exported {len(rows)} messages to {filename}")
        return filename
        
    def get_message_for_person(self, person_id: int, message_type: str = 'linkedin_connect') -> Optional[str]:
        """Retrieve a specific message for a person."""
        message = self.session.query(Message).filter(
            Message.person_id == person_id,
            Message.message_type == message_type
        ).order_by(
            Message.created_date.desc()
        ).first()
        
        return message.content if message else None
    
    # LinkedIn Sales Navigator API Integration (TO BE IMPLEMENTED)
    # This code is commented out as it would be implemented in the future
    
    def send_linkedin_messages(self, dry_run: bool = True):
        """Send LinkedIn connection requests via Sales Navigator API."""
        # Get all draft messages
        messages = self.session.query(Message, Person).join(Person).filter(
            Message.message_type == 'linkedin_connect',
            Message.status == 'draft'
        ).all()
        
        # LinkedIn Sales Navigator API credentials would be loaded here
        # api_key = os.getenv("LINKEDIN_API_KEY")
        # client_id = os.getenv("LINKEDIN_CLIENT_ID")
        # client_secret = os.getenv("LINKEDIN_CLIENT_SECRET")
        
        # Initialize LinkedIn API client
        # linkedin = LinkedInClient(api_key, client_id, client_secret)
        
        sent_count = 0
        for message, person in messages:
            try:
                # Log the message that would be sent
                logger.info(f"Would send to {person.name}: {message.content[:50]}...")
                
                if not dry_run:
                    # This would make the actual API call to LinkedIn
                    # response = linkedin.send_connection_request(
                    #     linkedin_id=person.linkedin,
                    #     message=message.content
                    # )
                    
                    # Update message status
                    # message.status = 'sent'
                    # message.sent_date = datetime.now()
                    # self.session.commit()
                    
                    sent_count += 1
                    
                    # Add delay to avoid LinkedIn rate limits
                    time.sleep(2)
            except Exception as e:
                logger.error(f"Error sending message to {person.name}: {e}")
                
        return sent_count
        
    def check_connection_status(self):
        """Check status of sent connection requests."""
        # Get all sent messages
        # messages = self.session.query(Message).filter(
        #     Message.message_type == 'linkedin_connect',
        #     Message.status == 'sent'
        # ).all()
        
        # Initialize LinkedIn API client
        # linkedin = LinkedInClient(api_key, client_id, client_secret)
        
        # for message in messages:
        #     person = message.person
        #     status = linkedin.get_connection_status(person.linkedin)
        #     
        #     if status == 'connected':
        #         message.status = 'connected'
        #         self.session.commit()
        #         
        #         # Generate follow-up message
        #         followup = self.generate_linkedin_followup(person)
        #         if followup:
        #             self.store_message(person.person_id, followup, 'linkedin_followup')
        
        pass


# For command-line execution
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Generate LinkedIn messages for executives")
    parser.add_argument(
        "-r", "--relevance", type=float, default=0.5,
        help="Minimum relevance score (0.0-1.0) for executives to message"
    )
    parser.add_argument(
        "-o", "--output", default="linkedin_messages.csv",
        help="Output CSV file for LinkedIn messages"
    )
    parser.add_argument(
        "-d", "--dry-run", action="store_true",
        help="Perform a dry run without sending messages (future functionality)"
    )
    args = parser.parse_args()
    
    messenger = LinkedInMessenger()
    messenger.generate_messages_for_all_executives(min_relevance=args.relevance)
    messenger.export_messages_to_csv(filename=args.output)
    
    # This would be uncommented when LinkedIn API integration is implemented
    # if not args.dry_run:
    #     messenger.send_linkedin_messages(dry_run=False)
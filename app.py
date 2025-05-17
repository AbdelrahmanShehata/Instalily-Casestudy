from flask import Flask, render_template, jsonify, request, redirect, url_for
import os
import pandas as pd
import json
import openai
from sqlalchemy import desc, func
from database_models import get_session, Event, Company, Person, Association, CompanyEvent

app = Flask(__name__)

# Load OpenAI API key from environment variables
from dotenv import load_dotenv
load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

def generate_icp_analysis(company, executives, events):
    """Generate an ICP analysis for a company using OpenAI."""
    try:
        # Prepare company data for the prompt
        company_info = {
            "name": company.name,
            "industry": company.industry or "Unknown",
            "revenue": company.estimated_revenue or "Unknown",
            "size": company.company_size or "Unknown",
            "description": company.description or "",
            "relevance_score": float(company.relevance_score or 0),
            "events": [{"name": e.name, "type": e.event_type} for e in events],
            "executives": [{"name": e.name, "title": e.title, "division": e.division} for e in executives]
        }
        
        # Create the prompt for OpenAI
        prompt = f"""
        Analyze the following company as a potential lead for DuPont Tedlar's protective PVF films for signage, graphics, and architecture:
        
        Company: {company_info['name']}
        Industry: {company_info['industry']}
        Revenue: {company_info['revenue']}
        Size: {company_info['size']}
        Relevance Score: {company_info['relevance_score']}
        Description: {company_info['description']}
        
        Associated Events:
        {json.dumps([e["name"] for e in company_info["events"]], indent=2)}
        
        Key Executives:
        {json.dumps([{"name": e["name"], "title": e["title"]} for e in company_info["executives"]], indent=2)}
        
        Generate a detailed ICP analysis in this exact format:
        
        **DuPont Tedlar's ICP**: **[COMPANY NAME]**.
        
        Why It's a Qualified Lead:
        * **Industry Fit** – [Analysis of how the company's industry aligns with Tedlar's target markets]
        * **Size & Revenue** – [Analysis of company size and revenue]
        * **Strategic Relevance** – [Analysis of the company's strategic importance in the signage/graphics industry]
        * **Industry Engagement** – [Analysis of the company's presence at trade shows and industry associations]
        * **Market Activity** – [Analysis of relevant market activities or trends]
        * **Decision-Maker Identified** – [Analysis of key decision makers and their relevance]
        
        For each bullet point, include specific facts and highlight key points in **bold**. Make the analysis specific to this company's actual data. If certain data points are missing, make reasonable inferences based on available information.
        """
        
        # Call OpenAI API
        response = openai.chat.completions.create(
            model="gpt-4-turbo-preview",
            messages=[
                {"role": "system", "content": "You are an expert in B2B sales qualification and lead analysis for the signage, graphics, and architectural films industry."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=1000
        )
        
        # Extract the generated analysis
        analysis = response.choices[0].message.content
        
        return analysis
    
    except Exception as e:
        print(f"Error generating ICP analysis: {e}")
        return f"""
        **DuPont Tedlar's ICP**: **{company.name}**
        
        *Error generating detailed analysis. Please try again later.*
        
        Basic qualification:
        * Industry: {company.industry or "Unknown"}
        * Revenue: {company.estimated_revenue or "Unknown"}
        * Size: {company.company_size or "Unknown"}
        * Relevance Score: {company.relevance_score or 0}
        """

@app.route('/')
def index():
    """Main dashboard page showing overview stats."""
    session = get_session()
    
    # Get counts for dashboard
    event_count = session.query(func.count(Event.event_id)).scalar()
    company_count = session.query(func.count(Company.company_id)).scalar()
    exec_count = session.query(func.count(Person.person_id)).scalar()
    assoc_count = session.query(func.count(Association.association_id)).scalar()
    
    # Get top events by relevance
    top_events = session.query(Event).order_by(desc(Event.relevance_score)).limit(5).all()
    
    # Get top companies by relevance
    top_companies = session.query(Company).order_by(desc(Company.relevance_score)).limit(5).all()
    
    # Get top executives by relevance
    top_execs = session.query(Person).order_by(desc(Person.relevance_score)).limit(5).all()
    
    return render_template('index.html', 
                           event_count=event_count,
                           company_count=company_count,
                           exec_count=exec_count,
                           assoc_count=assoc_count,
                           top_events=top_events,
                           top_companies=top_companies,
                           top_execs=top_execs)

@app.route('/events')
def events():
    """Page showing all events."""
    session = get_session()
    all_events = session.query(Event).order_by(desc(Event.relevance_score)).all()
    return render_template('events.html', events=all_events)

@app.route('/event/<int:event_id>')
def event_detail(event_id):
    """Page showing companies associated with an event."""
    session = get_session()
    event = session.query(Event).filter_by(event_id=event_id).first()
    
    if not event:
        return render_template('404.html', message=f"Event with ID {event_id} not found"), 404
    
    # Get companies associated with this event
    companies = session.query(Company).join(
        CompanyEvent, CompanyEvent.company_id == Company.company_id
    ).filter(
        CompanyEvent.event_id == event_id
    ).all()
    
    return render_template('event_detail.html', event=event, companies=companies)

@app.route('/companies')
def companies():
    """Page showing all companies."""
    session = get_session()
    all_companies = session.query(Company).order_by(desc(Company.relevance_score)).all()
    return render_template('companies.html', companies=all_companies)

@app.route('/company/<int:company_id>')
def company_detail(company_id):
    """Detailed view for a specific company with ICP analysis."""
    session = get_session()
    company = session.query(Company).filter_by(company_id=company_id).first()
    
    if not company:
        return render_template('404.html', message=f"Company with ID {company_id} not found"), 404
    
    # Get events associated with this company
    events = session.query(Event).join(
        CompanyEvent, CompanyEvent.event_id == Event.event_id
    ).filter(
        CompanyEvent.company_id == company_id
    ).all()
    
    # Get executives for this company
    executives = session.query(Person).filter_by(company_id=company_id).order_by(desc(Person.relevance_score)).all()
    
    # Get suggested personalized message for top executive (if any)
    top_exec = session.query(Person).filter_by(company_id=company_id).order_by(desc(Person.relevance_score)).first()
    
    # Generate ICP analysis
    regenerate = request.args.get('regenerate', 'false').lower() == 'true'
    
    # Check if we should generate a new analysis or use existing notes
    icp_analysis = None
    if regenerate or not company.notes:
        icp_analysis = generate_icp_analysis(company, executives, events)
        # Optionally save the analysis to the company notes
        if regenerate:
            company.notes = icp_analysis
            session.commit()
    else:
        # Use existing notes if they contain ICP analysis
        if "**DuPont Tedlar's ICP**" in (company.notes or ""):
            icp_analysis = company.notes
    
    # If we still don't have an analysis, generate one
    if not icp_analysis:
        icp_analysis = generate_icp_analysis(company, executives, events)
    
    return render_template('company_detail.html', 
                           company=company, 
                           events=events, 
                           executives=executives,
                           top_exec=top_exec,
                           icp_analysis=icp_analysis)

@app.route('/executives')
def executives():
    """Page showing all executives."""
    session = get_session()
    all_execs = session.query(Person).order_by(desc(Person.relevance_score)).all()
    return render_template('executives.html', executives=all_execs)

@app.route('/export_csv')
def export_csv():
    """Export data to CSV files."""
    session = get_session()
    
    # Export companies
    companies = session.query(Company).all()
    company_rows = []
    for c in companies:
        company_rows.append({
            "name": c.name,
            "industry": c.industry,
            "revenue": c.estimated_revenue,
            "size": c.company_size,
            "relevance": c.relevance_score,
            "website": c.website
        })
    pd.DataFrame(company_rows).to_csv('static/exports/companies.csv', index=False)
    
    # Export executives
    execs = session.query(Person, Company.name.label('company_name')).join(
        Company, Person.company_id == Company.company_id
    ).all()
    exec_rows = []
    for e, company_name in execs:
        exec_rows.append({
            "name": e.name,
            "title": e.title,
            "company": company_name,
            "email": e.email,
            "linkedin": e.linkedin,
            "division": e.division,
            "relevance": e.relevance_score
        })
    pd.DataFrame(exec_rows).to_csv('static/exports/executives.csv', index=False)
    
    # Export events
    events = session.query(Event).all()
    event_rows = []
    for e in events:
        event_rows.append({
            "name": e.name,
            "type": e.event_type,
            "start_date": e.start_date,
            "end_date": e.end_date,
            "location": e.location,
            "website": e.website,
            "relevance": e.relevance_score
        })
    pd.DataFrame(event_rows).to_csv('static/exports/events.csv', index=False)
    
    return redirect(url_for('index'))

@app.route('/api/company/<int:company_id>')
def api_company_detail(company_id):
    """API endpoint to get company details for AJAX calls."""
    session = get_session()
    company = session.query(Company).filter_by(company_id=company_id).first()
    
    if not company:
        return jsonify({"error": "Company not found"}), 404
    
    # Get executives for this company
    executives = session.query(Person).filter_by(company_id=company_id).order_by(desc(Person.relevance_score)).all()
    
    # Convert to JSON-serializable format
    execs_data = []
    for exec in executives:
        execs_data.append({
            'id': exec.person_id,
            'name': exec.name,
            'title': exec.title,
            'email': exec.email,
            'linkedin': exec.linkedin,
            'division': exec.division,
            'relevance_score': exec.relevance_score
        })
    
    return jsonify({
        'id': company.company_id,
        'name': company.name,
        'industry': company.industry,
        'description': company.description,
        'website': company.website,
        'revenue': company.estimated_revenue,
        'size': company.company_size,
        'relevance_score': company.relevance_score,
        'executives': execs_data
    })

if __name__ == '__main__':
    # Create export directory if it doesn't exist
    os.makedirs('static/exports', exist_ok=True)
    
    # Run the Flask app
    app.run(debug=False, port=5000)
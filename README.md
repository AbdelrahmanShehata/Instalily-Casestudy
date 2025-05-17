# DuPont Tedlar® AI Lead Generation System

An AI-powered B2B lead generation system for DuPont Tedlar® protective PVF films. This system discovers industry events, identifies potential customer companies, finds decision makers, and generates personalized outreach content.

## Table of Contents
1. [Project Overview](#project-overview)
2. [Installation](#installation)
3. [Configuration](#configuration)
4. [Running the Pipeline](#running-the-pipeline)
5. [Using the Dashboard](#using-the-dashboard)
6. [File Structure](#file-structure)
7. [Troubleshooting](#troubleshooting)

## Project Overview

This system uses a multi-agent AI architecture to:
- Discover relevant industry events and trade associations
- Identify and qualify potential customer companies
- Find decision makers at target companies
- Generate personalized LinkedIn outreach messages
- Provide an interactive dashboard for exploring leads

## Installation

### Prerequisites
- Python 3.9+ 
- pip (Python package installer)
- Git (optional)

### Setup

1. Clone or download this repository:
```bash
git clone [repository-url]
# or download and extract the ZIP file
```

2. Navigate to the project directory:
```bash
cd "C:\Users\Abdelrahman\Documents\Instalily CaseStudy"
```

3. Create and activate a virtual environment:
```bash
# Windows
python -m venv venv
venv\Scripts\activate

# macOS/Linux
python3 -m venv venv
source venv/bin/activate
```

4. Install required packages:
```bash
pip install -r requirements.txt
```

## Configuration

The system requires API keys for OpenAI and Serper. Create a `.env` file in the project root with the following:

```
# .env file
OPENAI_API_KEY=your_openai_api_key_here
SERPER_API_KEY=your_serper_api_key_here
DATABASE_URL=sqlite:///tedlar_leads.db
```

To obtain API keys:
- OpenAI API key: Sign up at [OpenAI Platform](https://platform.openai.com/)
- Serper API key: Register at [Serper.dev](https://serper.dev/)

## Running the Pipeline

The pipeline can be run end-to-end or in specific stages:

### Full Pipeline

Run the complete lead generation pipeline:
```bash
python pipeline.py
```

This will:
1. Generate and store events/associations
2. Discover companies related to these events
3. Find decision makers at these companies
4. Generate personalized LinkedIn messages
5. Export results to CSV files

### Custom Pipeline Options

```bash
# Run with custom parameters
python pipeline.py --queries 10 --results 20 --output-dir ./my_output --relevance 0.7

# Run with only certain steps
python pipeline.py --skip-leads --skip-companies  # Only do executive discovery and messaging

# Update relevance scores for existing companies
python pipeline.py --update-relevance --skip-leads --skip-companies
```

### Available Command-Line Options

- `-q, --queries`: Number of AI-generated search queries (default: 5)
- `-r, --results`: Number of web search results per query (default: 10)
- `-o, --output-dir`: Directory for output files (default: ./output)
- `-rel, --relevance`: Minimum relevance score for messaging (default: 0.5)
- `--update-relevance`: Update relevance scores for existing companies
- `--skip-leads`: Skip lead generation step
- `--skip-companies`: Skip company discovery step
- `--skip-executives`: Skip executive discovery step
- `--skip-messages`: Skip message generation step

## Using the Dashboard

The Flask dashboard provides an interactive interface to explore the lead database:

### Starting the Dashboard

```bash
python app.py
```

Then open your browser and navigate to: http://127.0.0.1:5000/

### Dashboard Features

- **Dashboard Overview**: Summary statistics and top entities
- **Events Page**: Browse and filter industry events
- **Companies Page**: Explore potential customer companies
- **Company Detail Pages**: View ICP analysis and decision makers
- **Executives Page**: Browse decision makers across companies
- **Export Options**: Download data as CSV files

## File Structure

```
C:\Users\Abdelrahman\Documents\Instalily CaseStudy\
├── app.py                    # Flask dashboard application
├── pipeline.py               # Main pipeline orchestration
├── lead_generator.py         # Event and association discovery
├── company_prioritization.py # Company discovery and scoring
├── decision_maker.py         # Executive discovery
├── messaging.py              # Outreach message generation
├── database_models.py        # SQLAlchemy database models
├── templates/                # Flask HTML templates
│   ├── base.html             # Base template
│   ├── index.html            # Dashboard home page
│   ├── companies.html        # Companies listing
│   └── ...                   # Other templates
├── static/                   # Static assets for Flask
│   ├── exports/              # Generated CSV files
├── requirements.txt          # Package dependencies
└── .env                      # Environment variables
```

## Troubleshooting

### Common Issues

**API Key Errors**:
- Ensure your `.env` file is in the root directory
- Check that your API keys are valid and have sufficient credits

**Database Errors**:
- If you get a "table already exists" error, the database is already initialized
- For other database errors, try deleting `tedlar_leads.db` and rerunning the pipeline

**SQLAlchemy Join Errors**:
- If you see "Can't determine which FROM clause to join from", ensure you're using the latest version of the code with explicit join paths

**OpenAI API Errors**:
- Rate limits: Add delays between API calls (adjust `time.sleep()` values)
- Token limits: Reduce the size of prompts or break them into smaller chunks

**Template Errors**:
- If you see Jinja2 syntax errors, ensure your template files are correctly formatted
- Check for issues with `or` operators in templates (use `|default()` or explicit if-else)

### Quick Access Commands

```bash
# Navigate to project directory
cd C:\Users\Abdelrahman\Documents\Instalily CaseStudy

# Activate virtual environment
venv\Scripts\activate

# Run the pipeline
python pipeline.py

# Run the dashboard
python app.py

# Stop the Flask server
# Press CTRL+C

# Deactivate virtual environment
deactivate
```

For questions or assistance, please contact the development team.

---

© 2025 DuPont Tedlar® AI Lead Generation System

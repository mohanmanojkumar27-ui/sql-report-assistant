# SQL Report Assistant 🤖

A LangGraph-powered tool that converts plain English business 
requirements into validated SQL queries — built to automate 
the manual report writing process in WACS (work and asset 
management systems.)

## What it does
This tool takes a plain English business requirement, validates it 
against your database schema, generates a SQL query, and waits for 
your approval before saving it as a .sql file. Built to replace the 
manual SQL report writing process in WACS asset management systems.

## How it works
1. User describes a report requirement in plain English
2. Agent checks if the requirement can be answered from the schema
3. Generates a SQL query using Google Gemini
4. Validates the query against a local SQLite database
5. Presents the SQL for human approval before saving
6. On rejection — rewrites and resubmits up to 3 times
7. Saves the approved query as a timestamped .sql file

## Tech Stack
- Python
- LangChain
- LangGraph
- Google Gemini API
- SQLite
- Pydantic


## Setup
1. Clone the repo
2. Run setup_db.py once to create the WACS database
3. Add your Gemini API key to .env: Gemini_API_Key=your_key
4. Run main.py

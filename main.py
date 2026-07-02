from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langgraph.types import interrupt,Command
from langgraph.graph import StateGraph, END
from langchain_core.output_parsers import StrOutputParser
from langgraph.checkpoint.memory import MemorySaver
from pydantic import BaseModel, Field
from typing import TypedDict, List
from datetime import datetime
from dotenv import load_dotenv
import os
import uuid
import sqlite3

load_dotenv()

llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0.3,
    google_api_key=os.getenv("Gemini_API_Key")
)

conn = sqlite3.connect("wacs.db")
cursor = conn.cursor()

class SQLUnderstanding(BaseModel):
    operation:    str       = Field(description="SQL operation needed eg SELECT INSERT")
    tables:       List[str] = Field(description="Table names required")
    columns:      List[str] = Field(description="Column names required")
    filters:      List[str] = Field(description="Filter conditions eg status = open")
    is_valid:     bool      = Field(description="Can the schema answer this requirement")
    schema_error: str       = Field(description="Why schema cannot answer it if invalid else empty string")

class SQLState(TypedDict):
    requirement:  str 
    understanding: SQLUnderstanding
    sql:          str        
    is_valid:     bool       
    error_msg:    str        
    approved:     bool       
    feedback:str
    file_path:    str        
    messages:     List[str]  
    retry_count:  int 

understand_prompt = ChatPromptTemplate.from_messages([
    ("system",
     "You are a SQL expert for WACS database.\n"
     "Schema:\n"
     "- work_orders(id, title, description, status, priority, created_date, completed_date, assigned_to)\n"
     "- work_requests(id, title, description, requested_by, status, created_date, work_order_id)\n"
     "- assets(id, asset_code, asset_name, asset_type, location, status, installation_date, last_maintenance_date)\n"
     "- work_activity(id, work_order_id, asset_id, activity_type, technician_name, start_date, end_date, hours_spent, notes)\n\n"
     "Decide if the user's requirement can be answered using this schema.\n"
     "If yes set is_valid True and extract the operation, tables, columns and filters needed.\n"
     "If no set is_valid False and explain why in schema_error.\n"
     "For columns — if user doesn't specify, return all relevant columns from the table."),
    ("human", "{requirement}")
])

generate_prompt=ChatPromptTemplate.from_messages([
    ("system",
     "You are a SQL expert for WACS database.\n"
     "Schema:\n"
     "- work_orders(id, title, description, status, priority, created_date, completed_date, assigned_to)\n"
     "- work_requests(id, title, description, requested_by, status, created_date, work_order_id)\n"
     "- assets(id, asset_code, asset_name, asset_type, location, status, installation_date, last_maintenance_date)\n"
     "- work_activity(id, work_order_id, asset_id, activity_type, technician_name, start_date, end_date, hours_spent, notes)\n"
     "Write ONLY the SQL query. No explanation. No markdown."),
     ("human",
    "Operation: {operation}\n"
     "Tables: {tables}\n"
     "Columns: {columns}\n"
     "Filters: {filters}")
      ])

fix_prompt = ChatPromptTemplate.from_messages([
    ("system",
     "You are a SQL expert for WACS database.\n"
     "You will be given a broken SQL query, an error message, and user feedback.\n"
     "Fix the query and return ONLY the corrected SQL. No explanation. No markdown."),
    ("human",
     "Broken SQL: {sql}\n"
     "Error: {error_msg}\n"
     "User feedback: {feedback}\n"
     "Return the fixed SQL only.")
])
      
parser = StrOutputParser()

understand_chain = understand_prompt | llm.with_structured_output(SQLUnderstanding)
generate_chain=generate_prompt| llm | parser
fix_chain=fix_prompt| llm | parser


def understand_node(state: SQLState) -> SQLState:
    result = understand_chain.invoke({"requirement": state["requirement"]})
    return {**state,"understanding":result}

def generate_node(state: SQLState) -> SQLState:
    understandings=state["understanding"]
    result=generate_chain.invoke({"operation":understandings.operation,
                                  "tables":    understandings.tables,
                                  "columns":   understandings.columns,
                                  "filters":   understandings.filters
                                  })
    return {**state, "sql": result}

def validate_node(state:SQLState)-> SQLState:
    try:
        query=state["sql"]
        cursor = conn.cursor()
        cursor.execute(query)
        rows = cursor.fetchall()    
        return {**state, "is_valid": True,"error_msg":""}
    except Exception as e:
         return {**state, "is_valid":False,"error_msg":str(e)}

def review_node(state:SQLState)-> SQLState:
     user_decision=interrupt("Do you approve this SQl?(yes/no):")
     comments=""
     if user_decision.strip().lower() == "no":
         comments= interrupt("What is wrong with it?: ")
     return {**state, "approved": user_decision.strip().lower() == "yes","feedback":comments}

def fix_node(state: SQLState) -> SQLState:
    result = fix_chain.invoke({
        "sql":      state["sql"],
        "error_msg": state["error_msg"],
        "feedback":  state["feedback"]
    })
    return {**state, "sql": result, "retry_count": state["retry_count"] + 1}

def write_node(state: SQLState) -> SQLState:
    filename = f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sql"
    filepath = os.path.join("output", filename)
    os.makedirs("output", exist_ok=True)
    with open(filepath, "w") as file:
        file.write(state["sql"])
    return {**state, "file_path": filepath}

def invalid_requirement_node(state: SQLState) -> SQLState:
    print(f"\nCannot generate SQL: {state['understanding'].schema_error}")
    return {**state}

def failed_node(state: SQLState) -> SQLState:
    print("\nMax retries reached. Could not generate valid SQL. Please rephrase your requirement.")
    return {**state}

def route_after_understand(state: SQLState) -> str:
    if state["understanding"].is_valid:
        return "generator"
    else:
        return "invalid_requirement"

def route_after_validation(state: SQLState) -> str:
    if state["retry_count"] >= 3:
        return "failed"
    elif state["is_valid"]:
        return "review"
    else:
        return "fix"

def route_after_review(state: SQLState) -> str:
    if state["approved"]:
        return "write"
    elif state["retry_count"] >= 3:
        return "failed"
    else:
        return "fix"

graph_builder = StateGraph(SQLState)

graph_builder.add_node("understand",understand_node)
graph_builder.add_node("generator",generate_node)
graph_builder.add_node("validator",validate_node)
graph_builder.add_node("reviewer",review_node)
graph_builder.add_node("fix",fix_node)
graph_builder.add_node("write",write_node)
graph_builder.add_node("failed", failed_node)
graph_builder.add_node("invalid_requirement", invalid_requirement_node)

graph_builder.set_entry_point("understand")
graph_builder.add_edge("generator","validator")
graph_builder.add_edge("fix","validator")
graph_builder.add_edge("write",END)
graph_builder.add_edge("failed", END)
graph_builder.add_edge("invalid_requirement", END)

graph_builder.add_conditional_edges(
    "understand",
    route_after_understand,
    {"generator": "generator", "invalid_requirement": "invalid_requirement"}
)


graph_builder.add_conditional_edges(
    "validator",
    route_after_validation,
    {"review": "reviewer", "fix": "fix", "failed": "failed"}
)

graph_builder.add_conditional_edges(
    "reviewer",
    route_after_review,
    {"write": "write", "fix": "fix","failed": "failed"})

memory = MemorySaver()
sql_graph = graph_builder.compile(checkpointer=memory)

if __name__ == "__main__":
    name = input("Hi! I am your Report Builder. What is your name? ").strip()
    print(f"\nNice to meet you, {name}! Ask me anything about your Reports.\n")

    while True:
        requirement = input("Your question (or 'exit' to quit): ").strip()
        if requirement.lower() == "exit":
            print("Goodbye! 👋")
            break
        config = {"configurable": {"thread_id": str(uuid.uuid4())}}
        result=sql_graph.invoke({
        "requirement": requirement,
        "understanding": "",
        "sql":        "",       
        "is_valid":   False,   
        "error_msg":   "",     
        "approved":    False,        
        "feedback":  "",
        "file_path":   "",    
        "messages":    [],
        "retry_count":  0,
        },config)

        while result.get("__interrupt__"):
            if "approve" in result["__interrupt__"][0].value.lower():
                print(f"\nGenerated SQL:\n{result['sql']}")
            user_input = input(result["__interrupt__"][0].value).strip()
            result = sql_graph.invoke(Command(resume=user_input), config)

        if result.get('file_path'):
            print(f"\nFile saved to: {result['file_path']}")

    




    

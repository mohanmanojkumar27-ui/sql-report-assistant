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
import logging
import time

load_dotenv()

llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0.3,
    google_api_key=os.getenv("Gemini_API_Key")
)

conn = sqlite3.connect("wacs.db")

logging.basicConfig(filename="sql_assistant.log",
                    level=logging.INFO,
                    format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

class SQLUnderstanding(BaseModel):
    operation:    str       = Field(description="SQL operation needed eg SELECT INSERT")
    tables:       List[str] = Field(description="Table names required")
    columns:      List[str] = Field(description="Column names required")
    filters:      List[str] = Field(description="Filter conditions eg status = open")
    is_valid:     bool      = Field(description="Can the schema answer this requirement")
    schema_error: str       = Field(description="Return a short reason (max 10 words) in schema_error. If the requirement cannot be answered using the schema.")

class SQLState(TypedDict):
    requirement:  str 
    understanding: SQLUnderstanding
    sql:          str    
    security_check:bool
    security_reason:str
    is_valid:     bool       
    error_msg:    str        
    approved:     bool       
    feedback:str
    file_path:    str        
    messages:     List[str]  
    retry_count:  int 

metrics = {"Total Requests": 0,
"SQL Queries Generated":0,
"Security Successes": 0,
"Security Failures":0,
"Validation Successes":0,
"Validation Failures":0,
"User Approvals":0,
"User Rejections": 0,
"Retries":0,
"Total Response Time":0
}

understand_prompt = ChatPromptTemplate.from_messages([
    ("system",
     "You are a SQL expert for the WACS database.\n\n"

     "Your job is to determine whether the user's request can be answered "
     "using the provided schema.\n\n"

     "Rules:\n"
     "1. This application supports ONLY SELECT queries.\n"
     "2. If the request is INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE or any other non-SELECT operation:\n"
     '   - is_valid = False\n'
     '   - schema_error = "Only SELECT queries are supported."\n'
     "3. If the request refers to tables or columns that do not exist in the schema:\n"
     '   - is_valid = False\n'
     '   - schema_error = "Requirement outside schema."\n'
     "4. If the request can be answered:\n"
     "   - is_valid = True\n"
     "   - Extract operation, tables, columns and filters.\n"
     "5. If the user does not specify columns, return all relevant columns.\n"
     "6. Never generate any explanation or reasoning in schema_error.\n"
     "7. schema_error must be exactly one of:\n"
     '   - "Only SELECT queries are supported."\n'
     '   - "Requirement outside schema."\n\n'
     "Schema:\n"
     "{schema}"
    ),
    ("human", "{requirement}")
])

generate_prompt=ChatPromptTemplate.from_messages([
    ("system",
     "You are a SQL expert for WACS database.\n"
     "Schema:\n"
     "{schema}\n\n"
    "Rules:\n"
    "1. Generate only a valid SQLite SELECT query.\n"
    "2. Never generate INSERT, UPDATE, DELETE, DROP, ALTER or TRUNCATE.\n"
    "3. Use only tables and columns present in the schema.\n"
    "4. Apply all user-requested filters.\n"
    "5. Return only SQL.\n"
    "6. No explanation.\n"
    "7. No markdown.\n"
    "\n"
    "Examples:\n"
    "Requirement: Show all open work orders\n"
    "SQL: SELECT * FROM work_orders WHERE status = 'open';\n\n"
    "Requirement: Show all high priority work orders assigned to John Smith\n"
    "SQL: SELECT * FROM work_orders WHERE priority = 'high' AND assigned_to = 'John Smith';\n\n"
    "Requirement: Count the number of completed work orders\n"
    "SQL: SELECT COUNT(*) AS completed_orders FROM work_orders WHERE status = 'completed';\n\n"
    "Requirement: Show work request titles with their work order status.\n"
    "SQL: SELECT wr.title, wo.status FROM work_requests wr JOIN work_orders wo ON wr.work_order_id = wo.id;\n"
    "Use the schema and rules above to generate the SQL query.\n"),
    ("human",
        "Operation: {operation}\n"
        "Filters: {filters}")
        ])

fix_prompt = ChatPromptTemplate.from_messages([
    ("system",
     "You are a SQL expert for WACS database.\n"
     "You will be given a broken SQL query, an error message, and user feedback.\n"
     "Generate only a valid SQLite SELECT query.\n"
     "Never generate INSERT, UPDATE, DELETE, DROP, ALTER or TRUNCATE.\n"
     "Use only tables and columns from the schema.\n"
     "Return only SQL.\n"
     "Fix the query and return ONLY the corrected SQL. No explanation. No markdown."),
    ("human",
     "Broken SQL: {sql}\n"
     "Error: {error_msg}\n"
     "User feedback: {feedback}\n"
     "Schema:\n"
     "{schema}")
])
      
parser = StrOutputParser()

understand_chain = understand_prompt | llm.with_structured_output(SQLUnderstanding)
generate_chain=generate_prompt| llm | parser
fix_chain=fix_prompt| llm | parser

schema_cache = None
def get_schema(conn):
    global schema_cache
    if schema_cache is not None:
        return schema_cache
    cursor = conn.cursor()
    cursor.execute("SELECT sql FROM sqlite_master WHERE type='table'")
    rows = cursor.fetchall()
    result = "\n".join([row[0] for row in rows if row[0]])
    schema_cache = result
    return result


def understand_node(state: SQLState) -> SQLState:
    result = understand_chain.invoke({"requirement": state["requirement"],"schema": get_schema(conn)})
    logger.info(f"Understanding generated: {result}, Requirement: {state['requirement']},operation:{result.operation}, filters: {result.filters}, is_valid: {result.is_valid}")
    return {**state,"understanding":result}

def generate_node(state: SQLState) -> SQLState:
    schema = get_schema(conn)
    understandings=state["understanding"]
    result=generate_chain.invoke({"schema":    schema,
                                  "operation":understandings.operation,
                                  "filters":   understandings.filters,
                                  })
    logger.info(f"SQL generated successfully | SQL: {result}")
    metrics["SQL Queries Generated"] += 1
    return {**state, "sql": result}

def security_node(state: SQLState) -> SQLState:
    query = state["sql"].strip().lower()
    
    dangerous = ["drop", "delete", "insert", "update", "alter", "truncate"]
    
    found = [word for word in dangerous if word in query]
    
    if found:
        logger.warning(f"Security check failed: {found} in query: {state['sql']}")
        metrics["Security Failures"] += 1
        return {**state, 
                "security_check": False, 
                "security_reason": f"Dangerous operation detected: {found}"}
    logger.info(f"Security check passed for query: {state['sql']}")
    metrics["Security Successes"] += 1
    return {**state, "security_check": True, "security_reason": ""}

def validate_node(state:SQLState)-> SQLState:
    try:
        query=state["sql"]
        cursor = conn.cursor()
        cursor.execute(query)
        rows = cursor.fetchall()    
        logger.info(f"Validation successful | SQL: {query}")
        metrics["Validation Successes"] += 1
        return {**state, "is_valid": True,"error_msg":""}
    except Exception as e:
         logger.error(f"Validation failed | SQL: {query} | Error: {str(e)}")
         metrics["Validation Failures"] += 1
         return {**state, "is_valid":False,"error_msg":str(e)}

def review_node(state:SQLState)-> SQLState:
     user_decision=interrupt("Do you approve this SQl?(yes/no):")
     comments = ""
     if user_decision.strip().lower() == "no":
         comments = interrupt("What is wrong with it?: ")

    
     if user_decision.strip().lower() == "yes":
        metrics["User Approvals"] += 1
        logger.info("User approved SQL")
     else:
        metrics["User Rejections"] += 1
        logger.info("User rejected SQL")
        logger.info(f"User feedback: {comments}")

     return {**state, "approved": user_decision.strip().lower() == "yes","feedback":comments}

def fix_node(state: SQLState) -> SQLState:
    schema=get_schema(conn)
    result = fix_chain.invoke({
        "sql":      state["sql"],
        "error_msg": state["error_msg"],
        "feedback":  state["feedback"],
        "schema":   schema
    })
    logger.info(f"Fixing SQL | Original: {state['sql']} | Error: {state['error_msg']} | Feedback: {state['feedback']} | Fixed: {result}")
    metrics["Retries"] += 1
    return {**state, "sql": result, "retry_count": state["retry_count"] + 1}

def write_node(state: SQLState) -> SQLState:
    filename = f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sql"
    filepath = os.path.join("output", filename)
    os.makedirs("output", exist_ok=True)
    with open(filepath, "w") as file:
        file.write(state["sql"])
    logger.info(f"SQL written to file: {filepath}")
    return {**state, "file_path": filepath}

def invalid_requirement_node(state: SQLState) -> SQLState:
    print(f"\nCannot generate SQL: {state['understanding'].schema_error}")
    logger.warning(f"Invalid requirement | Reason: {state['understanding'].schema_error}")
    return {**state}

def failed_node(state: SQLState) -> SQLState:
    print("\nMax retries reached. Could not generate valid SQL. Please rephrase your requirement.")
    logger.error("Max retries reached. Could not generate valid SQL.")
    return {**state}

def security_failed_node(state: SQLState) -> SQLState:
    print(f"\nCannot generate SQL: {state['security_reason']}")
    logger.warning(f"Security check failed | Reason: {state['security_reason']}")
    return {**state}

def route_after_understand(state: SQLState) -> str:
    if state["understanding"].is_valid:
        return "generator"
    else:
        return "invalid_requirement"

def route_after_security(state: SQLState) -> str:
    if state["security_check"]:
        return "validator"
    else:
        return "security_failed"

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
graph_builder.add_node("security",security_node)
graph_builder.add_node("validator",validate_node)
graph_builder.add_node("reviewer",review_node)
graph_builder.add_node("fix",fix_node)
graph_builder.add_node("write",write_node)
graph_builder.add_node("failed", failed_node)
graph_builder.add_node("security_failed", security_failed_node)
graph_builder.add_node("invalid_requirement", invalid_requirement_node)

graph_builder.set_entry_point("understand")
graph_builder.add_edge("generator","security")
graph_builder.add_edge("fix","security")
graph_builder.add_edge("write",END)
graph_builder.add_edge("failed", END)
graph_builder.add_edge("security_failed", END)
graph_builder.add_edge("invalid_requirement", END)

graph_builder.add_conditional_edges(
    "understand",
    route_after_understand,
    {"generator": "generator", "invalid_requirement": "invalid_requirement"}
)

graph_builder.add_conditional_edges(
    "security",
    route_after_security,
    {"validator": "validator", "security_failed": "security_failed"}
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
            print("\n========= METRICS =========")
            for k,v in metrics.items():
                print(f"{k}: {v}")
            if metrics["Total Requests"] > 0:
                Average_Response_Time = metrics["Total Response Time"] / metrics["Total Requests"]
                print(f"Average Response Time: {Average_Response_Time:.2f} seconds")
                logger.info(f"Session Metrics: {metrics}")
            print("Goodbye! 👋")
            break
        metrics["Total Requests"] += 1
        start_time = time.time()
        config = {"configurable": {"thread_id": str(uuid.uuid4())}}
        result=sql_graph.invoke({
        "requirement": requirement,
        "understanding": "",
        "sql":        "",   
        "security_check": False,
        "security_reason": "",    
        "is_valid":   False,   
        "error_msg":   "",     
        "approved":    False,        
        "feedback":  "",
        "file_path":   "",    
        "messages":    [],
        "retry_count":  0,
        },config)
        start_time = time.time()
        try:
            while result.get("__interrupt__"):
                if "approve" in result["__interrupt__"][0].value.lower():
                    print(f"\nGenerated SQL:\n{result['sql']}")
                user_input = input(result["__interrupt__"][0].value).strip()
                result = sql_graph.invoke(Command(resume=user_input), config)
            
            if result.get("file_path"):          
                print(f"\nFile saved to: {result['file_path']}")

        except Exception as e:
            print(f"\nSomething went wrong: {e}")
            logger.error(f"Graph execution failed: {e}")

        finally:
            end_time = time.time()               
            metrics["Total Response Time"] += end_time - start_time

    




    

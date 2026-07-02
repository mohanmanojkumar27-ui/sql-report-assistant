import sqlite3
import os

conn = sqlite3.connect("wacs.db")
cursor = conn.cursor()

cursor.execute("""
    CREATE TABLE IF NOT EXISTS work_orders (
        id              INTEGER PRIMARY KEY,
        title           TEXT,
        description     TEXT,
        status          TEXT,
        priority        TEXT,
        created_date    TEXT,
        completed_date  TEXT,
        assigned_to     TEXT
    )
""")

cursor.execute("""
    CREATE TABLE IF NOT EXISTS work_requests (
        id              INTEGER PRIMARY KEY,
        title           TEXT,
        description     TEXT,
        requested_by    TEXT,
        status          TEXT,
        created_date    TEXT,
        work_order_id   INTEGER,
        FOREIGN KEY (work_order_id) REFERENCES work_orders(id)
    )
""")

cursor.execute("""
    CREATE TABLE IF NOT EXISTS assets (
        id                      INTEGER PRIMARY KEY,
        asset_code              TEXT,
        asset_name              TEXT,
        asset_type              TEXT,
        location                TEXT,
        status                  TEXT,
        installation_date       TEXT,
        last_maintenance_date   TEXT
    )
""")

cursor.execute("""
    CREATE TABLE IF NOT EXISTS work_activity (
        id              INTEGER PRIMARY KEY,
        work_order_id   INTEGER,
        asset_id        INTEGER,
        activity_type   TEXT,
        technician_name TEXT,
        start_date      TEXT,
        end_date        TEXT,
        hours_spent     REAL,
        notes           TEXT,
        FOREIGN KEY (work_order_id) REFERENCES work_orders(id),
        FOREIGN KEY (asset_id)      REFERENCES assets(id)
    )
""")

cursor.executemany("""
    INSERT OR IGNORE INTO work_orders 
    VALUES (?,?,?,?,?,?,?,?)
""", [
    (1,  "Fix pump station A",        "Main pump failure at station A",         "open",      "high",   "2024-01-10", None,         "John Smith"),
    (2,  "Inspect pipeline section 3","Routine inspection of pipeline section 3","completed", "medium", "2024-01-05", "2024-01-08", "Sarah Jones"),
    (3,  "Replace valve V-204",       "Valve V-204 showing pressure issues",     "open",      "high",   "2024-01-12", None,         "John Smith"),
    (4,  "Electrical fault zone B",   "Electrical panel tripped in zone B",      "open",      "critical","2024-01-14",None,         "Mike Brown"),
    (5,  "Lubricate conveyor belt",   "Scheduled lubrication maintenance",       "completed", "low",    "2024-01-03", "2024-01-03", "Sarah Jones"),
    (6,  "Water leak repair",         "Detected water leak near asset A-10",     "open",      "high",   "2024-01-15", None,         "John Smith"),
    (7,  "Generator service",         "Annual service for backup generator",     "completed", "medium", "2023-12-20", "2023-12-22", "Mike Brown"),
    (8,  "Sensor calibration",        "Calibrate pressure sensors in block C",   "open",      "low",    "2024-01-16", None,         "Sarah Jones"),
    (9,  "Compressor overhaul",       "Full overhaul of compressor unit 2",      "in_progress","high",  "2024-01-11", None,         "John Smith"),
    (10, "CCTV camera repair",        "Camera offline at gate 4",                "completed", "medium", "2024-01-07", "2024-01-09", "Mike Brown"),
])

cursor.executemany("""
    INSERT OR IGNORE INTO work_requests
    VALUES (?,?,?,?,?,?,?)
""", [
    (1,  "Pump noise complaint",       "Unusual noise from pump A",           "Operations Team", "converted",  "2024-01-09", 1),
    (2,  "Pipeline check request",     "Request for pipeline inspection",     "Safety Team",     "converted",  "2024-01-04", 2),
    (3,  "Valve pressure drop",        "Reported pressure drop at V-204",     "Field Team",      "converted",  "2024-01-11", 3),
    (4,  "Power fluctuation report",   "Power fluctuations in zone B",        "Maintenance Team","converted",  "2024-01-13", 4),
    (5,  "Conveyor belt squeak",       "Belt making noise during operation",  "Operations Team", "converted",  "2024-01-02", 5),
    (6,  "Water puddle near A-10",     "Water found near asset A-10",         "Field Team",      "converted",  "2024-01-14", 6),
    (7,  "Generator check",            "Annual service reminder",             "Management",      "converted",  "2023-12-19", 7),
    (8,  "Sensor reading off",         "Pressure sensor giving odd readings", "Operations Team", "pending",    "2024-01-15", None),
    (9,  "Compressor vibration",       "Excessive vibration in compressor 2", "Field Team",      "converted",  "2024-01-10", 9),
    (10, "Camera not working",         "Gate 4 camera offline",               "Security Team",   "converted",  "2024-01-06", 10),
])

cursor.executemany("""
    INSERT OR IGNORE INTO assets
    VALUES (?,?,?,?,?,?,?,?)
""", [
    (1,  "PMP-001", "Pump Station A",       "Pump",       "Zone A", "active",       "2020-03-15", "2023-11-10"),
    (2,  "PMP-002", "Pump Station B",       "Pump",       "Zone B", "active",       "2020-03-15", "2023-10-05"),
    (3,  "VLV-204", "Valve V-204",          "Valve",      "Zone A", "faulty",       "2019-06-20", "2023-08-15"),
    (4,  "GEN-001", "Backup Generator",     "Generator",  "Zone C", "active",       "2018-01-10", "2023-12-22"),
    (5,  "CNV-001", "Conveyor Belt Unit 1", "Conveyor",   "Zone B", "active",       "2021-05-01", "2024-01-03"),
    (6,  "SEN-010", "Pressure Sensor C-1",  "Sensor",     "Zone C", "active",       "2022-02-14", "2023-09-01"),
    (7,  "CMP-002", "Compressor Unit 2",    "Compressor", "Zone A", "in_service",   "2019-11-30", "2023-07-20"),
    (8,  "CAM-004", "CCTV Camera Gate 4",   "Camera",     "Gate 4", "active",       "2021-08-25", "2024-01-09"),
    (9,  "PIP-003", "Pipeline Section 3",   "Pipeline",   "Zone B", "active",       "2017-04-10", "2024-01-08"),
    (10, "ELP-002", "Electrical Panel B",   "Electrical", "Zone B", "faulty",       "2018-09-05", "2023-06-15"),
])

cursor.executemany("""
    INSERT OR IGNORE INTO work_activity
    VALUES (?,?,?,?,?,?,?,?,?)
""", [
    (1,  1,  1,  "Inspection",   "John Smith",  "2024-01-10", "2024-01-10", 2.5, "Identified pump seal failure"),
    (2,  1,  1,  "Repair",       "John Smith",  "2024-01-11", "2024-01-11", 4.0, "Replaced pump seal"),
    (3,  2,  9,  "Inspection",   "Sarah Jones", "2024-01-05", "2024-01-08", 6.0, "No issues found"),
    (4,  3,  3,  "Inspection",   "John Smith",  "2024-01-12", "2024-01-12", 1.5, "Pressure drop confirmed"),
    (5,  4,  10, "Repair",       "Mike Brown",  "2024-01-14", "2024-01-14", 3.0, "Reset electrical panel"),
    (6,  5,  5,  "Maintenance",  "Sarah Jones", "2024-01-03", "2024-01-03", 1.0, "Lubrication completed"),
    (7,  6,  1,  "Inspection",   "John Smith",  "2024-01-15", "2024-01-15", 2.0, "Located leak source"),
    (8,  7,  4,  "Maintenance",  "Mike Brown",  "2023-12-20", "2023-12-22", 8.0, "Full annual service done"),
    (9,  9,  7,  "Overhaul",     "John Smith",  "2024-01-11", None,         5.0, "Overhaul in progress"),
    (10, 10, 8,  "Repair",       "Mike Brown",  "2024-01-07", "2024-01-09", 3.5, "Camera replaced"),
])

conn.commit()
conn.close()

print("WACS database created successfully at wacs.db")
print("Tables: work_orders, work_requests, assets, work_activity")
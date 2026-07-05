import os
import logging

def setup_incident_logging(incident_path):
    """
    Creates a 'logs' directory inside the incident folder and configures 
    the root logger to write to a file within it.
    """
    if not incident_path:
        return

    # 1. Create the logs directory
    logs_dir = os.path.join(incident_path, "logs")
    os.makedirs(logs_dir, exist_ok=True)

    log_file_path = os.path.join(logs_dir, "incident.log")
    abs_log_path = os.path.abspath(log_file_path)

    # 2. Get the root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # 3. Prevent adding duplicate file handlers if this function is called multiple times
    for handler in root_logger.handlers:
        if isinstance(handler, logging.FileHandler) and os.path.abspath(handler.baseFilename) == abs_log_path:
            return

    # 4. Create and configure the File Handler
    fh = logging.FileHandler(log_file_path, mode='a', encoding='utf-8')
    fh.setLevel(logging.DEBUG) # Captures DEBUG and above

    # 5. Create formatter
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    fh.setFormatter(formatter)

    # 6. Add handler to root logger
    root_logger.addHandler(fh)

    # Optional: Ensure there's a console handler so you still see logs in the terminal
    if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler) for h in root_logger.handlers):
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        ch.setFormatter(formatter)
        root_logger.addHandler(ch)

    root_logger.info(f"Logging initialized for incident: {incident_path}")

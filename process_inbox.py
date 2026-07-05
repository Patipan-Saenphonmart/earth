import fitz  # PyMuPDF
import os
import sys
import time
import shutil
from datetime import datetime

# Reconfigure stdout/stderr to use UTF-8 to prevent encoding crashes on Windows
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

# Constants
WORKSPACE = os.path.dirname(os.path.abspath(__file__)) if __file__ else "."
INBOX_DIR = os.path.join(WORKSPACE, "inbox")
FINISHED_DIR = os.path.join(WORKSPACE, "finished")
ARCHIVE_DIR = os.path.join(WORKSPACE, "archive")
FONT_PATH = os.path.join(WORKSPACE, "ArmRegular.ttf")

# Dashboard States
total_processed = 0
recent_activity = []
current_status = "Initializing..."

def log_activity(message):
    """Adds a log entry with the current timestamp and keeps the log list small."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    recent_activity.append(f"[{timestamp}] {message}")
    if len(recent_activity) > 8:  # Keep only the last 8 entries
        recent_activity.pop(0)

def draw_dashboard():
    """Clears the terminal and draws a beautiful, updated text dashboard."""
    # Clear console
    os.system('cls' if os.name == 'nt' else 'clear')
    
    try:
        inbox_files = [f for f in os.listdir(INBOX_DIR) if f.lower().endswith(".pdf")]
        inbox_count = len(inbox_files)
    except Exception:
        inbox_count = 0
        
    print("=====================================================================")
    print("      📄 PDF RED-TEXT FONT PROCESSOR (AUTOMATIC SYSTEM) 📄")
    print("=====================================================================")
    print(f" Status       : {current_status}")
    print(f" Font File    : {os.path.basename(FONT_PATH)} (ArmRegular)")
    print(f" Inbox Path   : {os.path.abspath(INBOX_DIR)}")
    print(f" Finished Path: {os.path.abspath(FINISHED_DIR)}")
    print(f" Backup Path  : {os.path.abspath(ARCHIVE_DIR)}")
    print("---------------------------------------------------------------------")
    print(f" Files waiting in Inbox : {inbox_count}")
    print(f" Total files processed  : {total_processed}")
    print("---------------------------------------------------------------------")
    print(" Recent Activity Logs:")
    if not recent_activity:
        print("   (No activity yet. Drop PDF files into the 'inbox' folder to start)")
    else:
        # Display logs in reverse (latest first)
        for log in reversed(recent_activity):
            print(f"   {log}")
    print("=====================================================================")
    print(" Press [Ctrl+C] to stop the system.")
    print("=====================================================================")

def setup_directories():
    """Creates the necessary directories if they do not exist."""
    for folder in [INBOX_DIR, FINISHED_DIR, ARCHIVE_DIR]:
        if not os.path.exists(folder):
            os.makedirs(folder)

def correct_thai_text(text):
    """
    Corrects spelling errors caused by character encoding mismatches in the PDF.
    Many instances of Sra Aa (U+0E32: า) were extracted as Sra Am (U+0E33: ำ).
    We map them back to U+0E32 and restore actual U+0E33 words dynamically.
    """
    # Remove spacing artifacts around Thai vowels
    corrected = text.replace(" ำ", "ำ").replace(" า", "า")
    
    # Map misencoded U+0E33 (ำ) to U+0E32 (า)
    corrected = corrected.replace("\u0e33", "\u0e32")
    
    # Restore correct U+0E33 (ำ) for words that genuinely need it in this document
    corrected = corrected.replace("น้า", "น้ำ")      # e.g., น้ำแข็ง
    corrected = corrected.replace("ทาให้", "ทำให้")  # e.g., ทำให้
    corrected = corrected.replace("จงนา", "จงนำ")    # e.g., จงนำ
    
    return corrected

def process_pdf(pdf_name):
    """Processes a single PDF file: redacts red text, replaces font, and corrects Thai spelling."""
    global total_processed, current_status
    
    input_path = os.path.join(INBOX_DIR, pdf_name)
    output_path = os.path.join(FINISHED_DIR, pdf_name)
    archive_path = os.path.join(ARCHIVE_DIR, pdf_name)
    
    current_status = f"Processing: {pdf_name}..."
    draw_dashboard()
    
    try:
        # Check if the file is completely copied and accessible
        with open(input_path, 'rb'):
            pass
    except IOError:
        log_activity(f"Locked: {pdf_name} (still copying?), retrying soon...")
        return False

    try:
        doc = fitz.open(input_path)
        modified_count = 0
        
        # CSS definition for custom font mapping
        css = """
        @font-face {
            font-family: 'ArmRegular';
            src: url('ArmRegular.ttf');
        }
        body {
            margin: 0;
            padding: 0;
        }
        """
        # Archive points to workspace directory containing ArmRegular.ttf
        archive = fitz.Archive(WORKSPACE)
        
        for page_num in range(len(doc)):
            page = doc[page_num]
            text_dict = page.get_text("dict")
            red_spans = []
            
            # Find spans with red color
            for block in text_dict.get("blocks", []):
                if "lines" in block:
                    for line in block["lines"]:
                        for span in line.get("spans", []):
                            color_int = span["color"]
                            r, g, b = fitz.sRGB_to_pdf(color_int)
                            
                            # Check color: red channel is dominant
                            if r > 0.7 and g < 0.3 and b < 0.3:
                                red_spans.append(span)
                                
            if not red_spans:
                continue
                
            # Redact the old text
            for span in red_spans:
                rect = fitz.Rect(span["bbox"])
                page.add_redact_annot(rect, fill=(1, 1, 1))
                
            # Apply redactions
            page.apply_redactions(images=0)
            
            # Insert the new text with the custom font
            for span in red_spans:
                rect = fitz.Rect(span["bbox"])
                rect.y0 -= 3
                rect.y1 += 3
                
                text = correct_thai_text(span["text"])
                size = span["size"]
                color_int = span["color"]
                r, g, b = fitz.sRGB_to_pdf(color_int)
                hex_color = f"#{int(r*255):02X}{int(g*255):02X}{int(b*255):02X}"
                
                html = f"""
                <div style="font-family: 'ArmRegular'; font-size: {size}pt; color: {hex_color}; line-height: 1.0; margin: 0; padding: 0;">
                    {text}
                </div>
                """
                
                try:
                    page.insert_htmlbox(rect, html, css=css, archive=archive)
                    modified_count += 1
                except Exception as e:
                    # Log internal errors inside the activity list
                    log_activity(f"Error on p.{page_num+1} ({text}): {str(e)[:20]}...")
                    
        # Save processed PDF to the finished folder
        doc.save(output_path)
        doc.close()
        
        # Move original file to archive folder to clear the inbox
        shutil.move(input_path, archive_path)
        
        total_processed += 1
        log_activity(f"Processed: {pdf_name} ({modified_count} spans replaced)")
        return True
        
    except Exception as e:
        log_activity(f"Failed: {pdf_name} - {str(e)}")
        # Move the failed file out of inbox to prevent infinite loops, but to archive with a fail prefix
        try:
            failed_archive_path = os.path.join(ARCHIVE_DIR, "FAILED_" + pdf_name)
            shutil.move(input_path, failed_archive_path)
            log_activity(f"Moved failed file to archive/FAILED_{pdf_name}")
        except Exception:
            pass
        return False

def scan_and_process():
    """Scans the inbox folder and processes any PDF files found."""
    try:
        files = [f for f in os.listdir(INBOX_DIR) if f.lower().endswith(".pdf")]
    except Exception:
        files = []
        
    if files:
        for filename in files:
            process_pdf(filename)

def main():
    global current_status
    setup_directories()
    
    if not os.path.exists(FONT_PATH):
        print(f"Error: Font file '{FONT_PATH}' not found in workspace root.")
        return
        
    current_status = "Monitoring Inbox..."
    
    try:
        while True:
            scan_and_process()
            current_status = "Monitoring Inbox..."
            draw_dashboard()
            time.sleep(2)  # Check every 2 seconds
    except KeyboardInterrupt:
        # Graceful exit
        os.system('cls' if os.name == 'nt' else 'clear')
        print("\n=====================================================")
        print("          ระบบการแปลงไฟล์ PDF ถูกหยุดการทำงานแล้ว")
        print("=====================================================")
        print(f" ผลงานรวมการแปลงไฟล์ในเซสชันนี้: {total_processed} ไฟล์")
        print(" ขอบคุณที่ใช้บริการครับ!")
        print("=====================================================\n")

if __name__ == "__main__":
    main()

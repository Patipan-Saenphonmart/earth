import fitz  # PyMuPDF
import os
import sys
import time
import shutil
from datetime import datetime

# Reconfigure stdout/stderr to use UTF-8 to prevent encoding crashes on Windows
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

# Try reconfiguring sys.stdin as well to catch UTF-8 inputs from modern consoles directly
try:
    sys.stdin.reconfigure(encoding='utf-8')
except Exception:
    pass

def recover_text(text):
    """Recovers Thai text from mistakenly decoded UTF-8 bytes in Windows CP1252/latin-1 terminal."""
    if not text:
        return ""
    try:
        # Try encoding using cp1252 first (standard Windows ANSI page)
        bytes_val = text.encode('cp1252')
        return bytes_val.decode('utf-8')
    except Exception:
        try:
            # Fallback to latin-1
            bytes_val = text.encode('latin-1')
            return bytes_val.decode('utf-8')
        except Exception:
            return text

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

def find_header_positions(page):
    """Searches for 'ชื่อ', 'ชั้น', 'เลขที่' labels on the page and returns their rects if aligned."""
    rects_name = page.search_for("ชื่อ")
    rects_class = page.search_for("ชั้น")
    rects_id = page.search_for("เลขที่")
    
    # Try to find a triplet on the same horizontal line (within 15 points)
    best_triplet = None
    min_y_diff = float('inf')
    
    for rn in rects_name:
        for rc in rects_class:
            for ri in rects_id:
                y_diff = abs(rn.y0 - rc.y0) + abs(rn.y0 - ri.y0)
                if y_diff < min_y_diff and y_diff < 15: # Must be reasonably aligned
                    min_y_diff = y_diff
                    best_triplet = (rn, rc, ri)
                    
    if best_triplet:
        return best_triplet
        
    # Fallback: find individually in the upper part of the page (usually header)
    rn_best = next((r for r in rects_name if r.y0 < 300), rects_name[0] if rects_name else None)
    rc_best = next((r for r in rects_class if r.y0 < 300), rects_class[0] if rects_class else None)
    ri_best = next((r for r in rects_id if r.y0 < 300), rects_id[0] if rects_id else None)
    return rn_best, rc_best, ri_best

def get_label_size(page, rect, default_size=16.0):
    """Finds the text span intersecting the given rect to retrieve the original font size."""
    if not rect:
        return default_size
    text_dict = page.get_text("dict")
    for block in text_dict.get("blocks", []):
        if "lines" in block:
            for line in block["lines"]:
                for span in line.get("spans", []):
                    span_rect = fitz.Rect(span["bbox"])
                    if span_rect.intersects(rect):
                        return span["size"]
    return default_size

def get_right_boundary(r_start, other_rects, page_width, default_width=200):
    """Calculates the right boundary coordinate for writing text next to a label."""
    # Find all other rects that are on the same line (y0 difference < 15) and to the right (x0 > r_start.x1)
    right_rects = [r for r in other_rects if r and abs(r.y0 - r_start.y0) < 15 and r.x0 > r_start.x1]
    if right_rects:
        # Sort them by x0 to find the closest one
        right_rects.sort(key=lambda r: r.x0)
        return right_rects[0].x0 - 5
    else:
        return min(r_start.x1 + default_width, page_width - 20)

def fill_student_info(page, name_text, class_text, id_text, handwriting_color):
    """Cover the dots after labels and insert Name, Class, and ID using handwriting font."""
    rn, rc, ri = find_header_positions(page)
    
    # If none of the labels are found on this page, do nothing
    if not rn and not rc and not ri:
        return
        
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
    archive = fitz.Archive(WORKSPACE)
    
    # Default to blue color for student handwriting fields if not specified
    text_color = handwriting_color if handwriting_color else "#0000FF"
    
    # 1. Insert Name
    if rn and name_text:
        x1 = get_right_boundary(rn, [rc, ri], page.rect.width, default_width=250)
        rect = fitz.Rect(rn.x1 + 5, rn.y0 - 3, x1, rn.y1 + 3)
        
        size = get_label_size(page, rn)
        html = f"""
        <div style="font-family: 'ArmRegular'; font-size: {size}pt; color: {text_color}; line-height: 1.0; margin: 0; padding: 0;">
            {name_text}
        </div>
        """
        try:
            page.insert_htmlbox(rect, html, css=css, archive=archive)
        except Exception:
            pass
            
    # 2. Insert Class
    if rc and class_text:
        x1 = get_right_boundary(rc, [rn, ri], page.rect.width, default_width=100)
        rect = fitz.Rect(rc.x1 + 5, rc.y0 - 3, x1, rc.y1 + 3)
        
        size = get_label_size(page, rc)
        html = f"""
        <div style="font-family: 'ArmRegular'; font-size: {size}pt; color: {text_color}; line-height: 1.0; margin: 0; padding: 0;">
            {class_text}
        </div>
        """
        try:
            page.insert_htmlbox(rect, html, css=css, archive=archive)
        except Exception:
            pass
            
    # 3. Insert ID
    if ri and id_text:
        x1 = get_right_boundary(ri, [rn, rc], page.rect.width, default_width=80)
        rect = fitz.Rect(ri.x1 + 5, ri.y0 - 3, x1, ri.y1 + 3)
        
        size = get_label_size(page, ri)
        html = f"""
        <div style="font-family: 'ArmRegular'; font-size: {size}pt; color: {text_color}; line-height: 1.0; margin: 0; padding: 0;">
            {id_text}
        </div>
        """
        try:
            page.insert_htmlbox(rect, html, css=css, archive=archive)
        except Exception:
            pass

def merge_outputs(pdf_paths):
    """Merges multiple PDF files into a single timestamped file and returns the path."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    merged_filename = f"merged_{timestamp}.pdf"
    merged_path = os.path.join(FINISHED_DIR, merged_filename)
    
    global current_status
    current_status = f"Merging {len(pdf_paths)} files..."
    draw_dashboard()
    
    try:
        merged_doc = fitz.open()
        for path in pdf_paths:
            if os.path.exists(path):
                doc = fitz.open(path)
                merged_doc.insert_pdf(doc)
                doc.close()
        merged_doc.save(merged_path)
        merged_doc.close()
        log_activity(f"Merged {len(pdf_paths)} files into: {merged_filename}")
        return merged_path
    except Exception as e:
        log_activity(f"Failed to merge files: {str(e)}")
        return None

def convert_pdf_to_png(pdf_path):
    """Converts each page of the PDF to a PNG image with good quality but optimized size."""
    if not os.path.exists(pdf_path):
        return False
    
    try:
        pdf_dir = os.path.dirname(pdf_path)
        pdf_basename = os.path.basename(pdf_path)
        pdf_name_without_ext = os.path.splitext(pdf_basename)[0]
        png_dir = os.path.join(pdf_dir, pdf_name_without_ext + "_png")
        
        if not os.path.exists(png_dir):
            os.makedirs(png_dir)
            
        doc = fitz.open(pdf_path)
        total_pages = len(doc)
        
        global current_status
        current_status = f"Converting to PNG..."
        draw_dashboard()
        
        log_activity(f"Converting {pdf_basename} to PNGs...")
        
        for page_num in range(total_pages):
            page = doc[page_num]
            # Zoom factor 2.0 corresponds to 144 DPI, which is clear but not excessively heavy
            zoom = 2.0
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat)
            
            png_filename = f"page_{page_num + 1:03d}.png"
            png_path = os.path.join(png_dir, png_filename)
            pix.save(png_path)
            
        doc.close()
        log_activity(f"Saved {total_pages} PNGs to: {pdf_name_without_ext}_png")
        return True
    except Exception as e:
        log_activity(f"Failed to convert PDF to PNG: {str(e)}")
        return False

def process_pdf(pdf_name, handwriting_color=None, name_text="", class_text="", id_text=""):
    """Processes a single PDF file: redacts red text, replaces font, corrects spelling, and inserts student details."""
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
            
            # Fill student info on this page if the labels are found
            fill_student_info(page, name_text, class_text, id_text, handwriting_color)
            
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
                # Redact the text without drawing a colored fill (keeps background/dotted lines intact)
                page.add_redact_annot(rect)
                
            # Apply redactions (graphics=0 keeps dotted lines intact)
            page.apply_redactions(images=0, graphics=0)
            
            # Insert the new text with the custom font
            for span in red_spans:
                rect = fitz.Rect(span["bbox"])
                size = span["size"]
                
                # Redraw dots in black to restore the dotted line deleted by redaction
                w = rect.x1 - rect.x0
                dot_width = size * 0.22
                num_dots = int(w / dot_width)
                dots_text = "." * num_dots
                page.insert_text(fitz.Point(rect.x0, rect.y1 - 2), dots_text, fontsize=size, fontname="helv", color=(0, 0, 0))
                
                rect.y0 -= 3
                rect.y1 += 3
                
                text = correct_thai_text(span["text"])
                size = span["size"]
                color_int = span["color"]
                r, g, b = fitz.sRGB_to_pdf(color_int)
                original_hex = f"#{int(r*255):02X}{int(g*255):02X}{int(b*255):02X}"
                hex_color = handwriting_color if handwriting_color else original_hex
                
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

def scan_and_process(handwriting_color, name_text, class_text, id_text):
    """Scans the inbox folder and processes any PDF files found, merging them if multiple."""
    try:
        files = [f for f in os.listdir(INBOX_DIR) if f.lower().endswith(".pdf")]
    except Exception:
        files = []
        
    if files:
        # Sort files to ensure deterministic alphabetical order for processing and merging
        files.sort()
        
        processed_outputs = []
        for filename in files:
            output_path = os.path.join(FINISHED_DIR, filename)
            if process_pdf(filename, handwriting_color, name_text, class_text, id_text):
                processed_outputs.append(output_path)
                
        # Merge if there are multiple outputs processed in this batch
        if len(processed_outputs) > 1:
            merged_path = merge_outputs(processed_outputs)
            if merged_path:
                convert_pdf_to_png(merged_path)

def main():
    global current_status
    setup_directories()
    
    if not os.path.exists(FONT_PATH):
        print(f"Error: Font file '{FONT_PATH}' not found in workspace root.")
        return
        
    print("=====================================================================")
    print("      📄 PDF RED-TEXT FONT PROCESSOR (CONFIGURING SETTINGS) 📄")
    print("=====================================================================")
    
    # 1. Color Selection
    print("เลือกสีตัวอักษรสำหรับการแปลงเป็นฟอนต์ลายมือ (Handwriting Text Color):")
    print(" 1. สีเดิมในไฟล์ PDF (Keep Original) [ค่าเริ่มต้น]")
    print(" 2. สีน้ำเงิน (Blue)")
    print(" 3. สีดำ (Black)")
    print(" 4. สีแดง (Red)")
    print(" 5. กำหนดรหัสสี Hex เอง (เช่น #FF00FF)")
    color_choice = input("กรอกหมายเลขตัวเลือก (1-5): ").strip()
    
    handwriting_color = None
    if color_choice == "2":
        handwriting_color = "#0000FF"
    elif color_choice == "3":
        handwriting_color = "#000000"
    elif color_choice == "4":
        handwriting_color = "#FF0000"
    elif color_choice == "5":
        hex_input = recover_text(input("กรอกรหัสสี Hex (เช่น #FF00FF): ").strip())
        if hex_input:
            if not hex_input.startswith("#"):
                hex_input = "#" + hex_input
            handwriting_color = hex_input
            
    print("---------------------------------------------------------------------")
    # 2. Student Info Inputs
    print("กรอกข้อมูลนักเรียนเพื่อนำไปวางในไฟล์ PDF (หากไม่ต้องการกรอกให้กด Enter ข้าม):")
    name_text = recover_text(input("ชื่อ-นามสกุล (Name): ").strip())
    class_text = recover_text(input("ชั้น (Class): ").strip())
    id_text = recover_text(input("เลขที่ (ID): ").strip())
    
    print("---------------------------------------------------------------------")
    print("กำลังเริ่มระบบตรวจสอบไฟล์ใน inbox...")
    time.sleep(1.5)
    
    current_status = "Monitoring Inbox..."
    
    try:
        while True:
            scan_and_process(handwriting_color, name_text, class_text, id_text)
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

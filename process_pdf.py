import fitz  # PyMuPDF
import os
import sys

# Reconfigure stdout/stderr to use UTF-8 to prevent encoding crashes on Windows
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

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

def main():
    pdf_path = "แบบฝึกหัดท้ายบท.pdf"
    font_path = "ArmRegular.ttf"
    output_path = "แบบฝึกหัดท้ายบท_modified.pdf"
    
    if not os.path.exists(pdf_path):
        print(f"Error: Input PDF '{pdf_path}' not found.")
        return
    if not os.path.exists(font_path):
        print(f"Error: Font file '{font_path}' not found.")
        return
        
    doc = fitz.open(pdf_path)
    print(f"Opened PDF: {pdf_path} ({len(doc)} pages)")
    
    # Step 1: Scan for unique colors to understand the document structure
    print("\n--- Scanning PDF for text colors ---")
    unique_colors = {}
    total_spans = 0
    
    for page_num in range(len(doc)):
        page = doc[page_num]
        text_dict = page.get_text("dict")
        for block in text_dict.get("blocks", []):
            if "lines" in block:
                for line in block["lines"]:
                    for span in line.get("spans", []):
                        total_spans += 1
                        color_int = span["color"]
                        r, g, b = fitz.sRGB_to_pdf(color_int)
                        # Format as hex color
                        color_hex = f"#{int(r*255):02X}{int(g*255):02X}{int(b*255):02X}"
                        
                        if color_hex not in unique_colors:
                            unique_colors[color_hex] = []
                        if len(unique_colors[color_hex]) < 3:
                            # Save text sample
                            unique_colors[color_hex].append(span["text"])
                            
    print(f"Total spans found: {total_spans}")
    print("Unique colors and text samples:")
    for hex_color, samples in unique_colors.items():
        print(f"  {hex_color}: {samples}")
        
    # Step 2: Replace red text font
    print("\n--- Replacing red text font ---")
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
    # Archive points to current directory containing ArmRegular.ttf
    archive = fitz.Archive(".")
    
    for page_num in range(len(doc)):
        page = doc[page_num]
        text_dict = page.get_text("dict")
        red_spans = []
        
        # Find spans with red color
        # Red: R is high (e.g. > 0.7), G and B are low (e.g. < 0.3)
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
            
        print(f"Page {page_num + 1}: Found {len(red_spans)} red spans to modify")
        
        # Redact the old text using original tight bounding box
        for span in red_spans:
            rect = fitz.Rect(span["bbox"])
            # Redact using white fill to cover old text
            page.add_redact_annot(rect, fill=(1, 1, 1))
            
        # Apply redactions FIRST before rendering new text
        page.apply_redactions(images=0)
        
        # Insert the new text with the custom font using insert_htmlbox (with HarfBuzz complex shaping)
        for span in red_spans:
            rect = fitz.Rect(span["bbox"])
            
            # Expand the rect vertically to prevent vertical clipping of Thai tone marks and vowels
            rect.y0 -= 3
            rect.y1 += 3
            
            # Correct spelling of text extracted from PDF
            text = correct_thai_text(span["text"])
            
            size = span["size"]
            color_int = span["color"]
            r, g, b = fitz.sRGB_to_pdf(color_int)
            hex_color = f"#{int(r*255):02X}{int(g*255):02X}{int(b*255):02X}"
            
            # HTML template for text layout shaping
            html = f"""
            <div style="font-family: 'ArmRegular'; font-size: {size}pt; color: {hex_color}; line-height: 1.0; margin: 0; padding: 0;">
                {text}
            </div>
            """
            
            try:
                page.insert_htmlbox(rect, html, css=css, archive=archive)
                modified_count += 1
            except Exception as e:
                print(f"  Error inserting text '{text}' on page {page_num + 1}: {e}")
                
    doc.save(output_path)
    print(f"\nSuccessfully saved modified PDF to '{output_path}'")
    print(f"Total red text spans processed: {modified_count}")

if __name__ == "__main__":
    main()

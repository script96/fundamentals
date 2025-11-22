import customtkinter as ctk
import tkinter as tk
from tkinter import StringVar
import re

# --- Lexical Analyzer ---
token_specification = [
    ("NUMBER", r'\d+(\.\d+)?'),
    ("ASSIGN", r'='),
    ("ID", r'[A-Za-z_]\w*'),
    ("OP", r'[+\-*/]'),
    ("LPAREN", r'\('),
    ("RPAREN", r'\)'),
    ("SKIP", r'[ \t\n]+'),
    ("MISMATCH", r'.'),
]
tok_regex = '|'.join(f'(?P<{name}>{pattern})' for name, pattern in token_specification)


def lexer(code):
    tokens, symbol_table, id_counter = [], {}, 1
    prev_token_kind = None
    
    for mo in re.finditer(tok_regex, code):
        kind, value = mo.lastgroup, mo.group()
        
        # Check for invalid token sequences (NUMBER followed by ID without operator)
        if prev_token_kind == "NUMBER" and kind == "ID":
            raise RuntimeError(f"Syntax error: number cannot be directly followed by identifier '{value}' without an operator")
        
        if kind == "ID":
            if value not in symbol_table:
                symbol_table[value] = f'id{id_counter}'
                id_counter += 1
            tokens.append(('ID', symbol_table[value], value))
            prev_token_kind = "ID"
        elif kind in ["NUMBER", "ASSIGN", "OP", "LPAREN", "RPAREN"]:
            tokens.append((kind, value))
            prev_token_kind = kind
        elif kind == "SKIP":
            continue
        else:
            raise RuntimeError(f"Unexpected character {value!r}")
    return tokens, symbol_table


# --- Syntax Analyzer ---
class Node:
    def __init__(self, value, left=None, right=None, node_type="OP", original_name=None):
        self.value, self.left, self.right = value, left, right
        self.node_type, self.original_name = node_type, original_name
        self.type_info = None


class Parser:
    def __init__(self, tokens):
        self.tokens, self.pos = tokens, 0

    def current_token(self):
        return self.tokens[self.pos] if self.pos < len(self.tokens) else (None, None, None)

    def eat(self, expected_kind):
        token = self.current_token()
        if token[0] == expected_kind:
            self.pos += 1
            return token
        raise SyntaxError(f"Expected {expected_kind} but found {token[0]}")

    def parse(self):
        return self.statement()

    def statement(self):
        id_token = self.eat('ID')
        left = Node(id_token[1], node_type='ID', original_name=id_token[2])
        op_token = self.eat('ASSIGN')
        right = self.expression()
        return Node(op_token[1], left, right, node_type='ASSIGN')

    def expression(self):
        node = self.term()
        while self.current_token()[0] == 'OP' and self.current_token()[1] in '+-':
            op = self.eat('OP')
            node = Node(op[1], node, self.term())
        return node

    def term(self):
        node = self.factor()
        while self.current_token()[0] == 'OP' and self.current_token()[1] in '*/':
            op = self.eat('OP')
            node = Node(op[1], node, self.factor())
        return node

    def factor(self):
        kind, value, *_ = self.current_token()
        if kind == 'NUMBER':
            self.eat('NUMBER')
            return Node(value, node_type='NUMBER')
        if kind == 'ID':
            id_token = self.eat('ID')
            return Node(id_token[1], node_type='ID', original_name=id_token[2])
        if kind == 'LPAREN':
            self.eat('LPAREN')
            node = self.expression()
            self.eat('RPAREN')
            return node
        raise SyntaxError(f"Unexpected token {kind}")


# --- Semantic Analyzer ---
def get_type(node, type_table):
    if node.type_info == "int to float": return 'float'
    if node.node_type == 'NUMBER': return 'float' if '.' in str(node.value) else 'int'
    if node.node_type == 'ID': return type_table.get(node.original_name, 'int')
    if node.node_type in ['OP', 'ASSIGN'] and node.left and node.right:
        is_float = get_type(node.left, type_table) == 'float' or get_type(node.right, type_table) == 'float'
        return 'float' if is_float else 'int'
    return None


def mark_leaves_for_coercion(node):
    if not node: return
    if node.node_type in ['ID', 'NUMBER'] and not (node.node_type == 'NUMBER' and '.' in node.value):
        node.type_info = "int to float"
    else:
        mark_leaves_for_coercion(node.left)
        mark_leaves_for_coercion(node.right)


def semantic_analysis(node, type_table):
    if not node: return
    semantic_analysis(node.left, type_table)
    semantic_analysis(node.right, type_table)
    if node.node_type in ["OP", "ASSIGN"] and node.left and node.right:
        left_type, right_type = get_type(node.left, type_table), get_type(node.right, type_table)
        if left_type != right_type:
            if left_type == 'int': mark_leaves_for_coercion(node.left)
            if right_type == 'int': mark_leaves_for_coercion(node.right)


# --- Intermediate Code Generator ---
def collect_conversions(node, type_table, conversions, temp_counter, skip_left_assign=False):
    """Collect all type conversions needed upfront"""
    if not node:
        return temp_counter
    
    # Skip the left side of assignment (the variable being assigned to)
    if skip_left_assign and node.node_type == 'ASSIGN':
        # Only collect from the right side (the expression)
        temp_counter = collect_conversions(node.right, type_table, conversions, temp_counter, False)
        return temp_counter
    
    # Handle leaf nodes that need conversion
    if node.node_type in ['ID', 'NUMBER'] and node.type_info == "int to float":
        # Create a unique key for this conversion
        if node.node_type == 'ID':
            key = ('ID', node.original_name)
            if key not in conversions:
                temp_name = f"temp{temp_counter}"
                temp_counter += 1
                conversions[key] = (temp_name, f"{temp_name} = float({node.original_name})")
        elif node.node_type == 'NUMBER':
            key = ('NUMBER', node.value)
            if key not in conversions:
                temp_name = f"temp{temp_counter}"
                temp_counter += 1
                conversions[key] = (temp_name, f"{temp_name} = float({node.value})")
    
    # Recursively collect from children
    temp_counter = collect_conversions(node.left, type_table, conversions, temp_counter, False)
    temp_counter = collect_conversions(node.right, type_table, conversions, temp_counter, False)
    
    return temp_counter


def generate_icg(node, type_table, instructions, temp_counter, conversions=None):
    """Generate three-address code from semantic tree"""
    if not node:
        return None, temp_counter
    
    # Handle leaf nodes (ID and NUMBER)
    if node.node_type == 'ID':
        var_name = node.original_name
        
        # If this ID needs type conversion, return the temp that was created upfront
        if node.type_info == "int to float":
            key = ('ID', var_name)
            if conversions and key in conversions:
                return conversions[key][0], temp_counter
        
        return var_name, temp_counter
    
    elif node.node_type == 'NUMBER':
        # If number needs conversion, return the temp that was created upfront
        if node.type_info == "int to float":
            key = ('NUMBER', node.value)
            if conversions and key in conversions:
                return conversions[key][0], temp_counter
        
        return node.value, temp_counter
    
    # Handle assignment node
    elif node.node_type == 'ASSIGN':
        # Generate code for the right side (expression)
        right_result, temp_counter = generate_icg(node.right, type_table, instructions, temp_counter, conversions)
        # Assign to the left side variable
        var_name = node.left.original_name
        instructions.append(f"{var_name} = {right_result}")
        return var_name, temp_counter
    
    # Handle operators
    elif node.node_type == 'OP':
        # Generate code for left operand
        left_result, temp_counter = generate_icg(node.left, type_table, instructions, temp_counter, conversions)
        # Generate code for right operand
        right_result, temp_counter = generate_icg(node.right, type_table, instructions, temp_counter, conversions)
        
        # Create a new temp for this operation
        temp_name = f"temp{temp_counter}"
        temp_counter += 1
        instructions.append(f"{temp_name} = {left_result} {node.value} {right_result}")
        return temp_name, temp_counter
    
    return None, temp_counter


# --- Modern Dark GUI using CTk ---
class CompilerGUI(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Modern Compiler Analyzer")
        self.geometry("900x900")

        # Enable dark mode
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.tokens, self.type_vars = [], {}

        # Create main scrollable frame
        self.main_frame = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.main_frame.pack(fill="both", expand=True, padx=5, pady=5)

        # --- Source Code Input ---
        self.code_label = ctk.CTkLabel(self.main_frame, text="Source Code", font=("Segoe UI", 18, "bold"))
        self.code_label.pack(pady=(10, 0))

        self.code_input = ctk.CTkTextbox(self.main_frame, height=100, font=("Consolas", 13))
        self.code_input.pack(padx=15, pady=10, fill="x")
        self.code_input.insert("0.0", "Z = 2 * y + 2.9 * X")

        # --- Buttons ---
        self.button_frame = ctk.CTkFrame(self.main_frame)
        self.button_frame.pack(pady=10)

        self.analyze_button = ctk.CTkButton(self.button_frame, text="1. Analyze Code & Set Types", command=self.run_lexical)
        self.analyze_button.grid(row=0, column=0, padx=10)

        self.generate_button = ctk.CTkButton(self.button_frame, text="2. Generate Trees", command=self.run_parsing, state="disabled")
        self.generate_button.grid(row=0, column=1, padx=10)

        # --- Lexical Output ---
        self.lexical_label = ctk.CTkLabel(self.main_frame, text="Lexical Analyzer", font=("Segoe UI", 16, "bold"))
        self.lexical_label.pack(pady=(10, 0))

        self.lexical_output = ctk.CTkTextbox(self.main_frame, height=80, font=("Consolas", 12))
        self.lexical_output.pack(padx=15, pady=5, fill="x")

        # --- Variable Type Selector ---
        self.type_frame = ctk.CTkFrame(self.main_frame)
        self.type_frame.pack(padx=10, pady=10, fill="x")

        # --- Syntax Tree ---
        self.syntax_label = ctk.CTkLabel(self.main_frame, text="Syntax Tree", font=("Segoe UI", 16, "bold"))
        self.syntax_label.pack(pady=(10, 0))
        self.syntax_canvas = tk.Canvas(self.main_frame, bg="#1E1E1E", highlightthickness=1, highlightbackground="#333", height=200)
        self.syntax_canvas.pack(padx=10, pady=5, fill="x")

        # --- Semantic Tree ---
        self.semantic_label = ctk.CTkLabel(self.main_frame, text="Semantic Tree", font=("Segoe UI", 16, "bold"))
        self.semantic_label.pack(pady=(10, 0))
        self.semantic_canvas = tk.Canvas(self.main_frame, bg="#1E1E1E", highlightthickness=1, highlightbackground="#333", height=200)
        self.semantic_canvas.pack(padx=10, pady=5, fill="x")

        # --- ICG Output ---
        self.icg_label = ctk.CTkLabel(self.main_frame, text="Intermediate Code Generation (ICG)", font=("Segoe UI", 16, "bold"))
        self.icg_label.pack(pady=(10, 0))
        self.icg_output = ctk.CTkTextbox(self.main_frame, height=120, font=("Consolas", 12))
        self.icg_output.pack(padx=15, pady=(5, 15), fill="x")

    def run_lexical(self):
        for widget in self.type_frame.winfo_children(): widget.destroy()
        self.lexical_output.delete("1.0", tk.END)
        self.syntax_canvas.delete("all")
        self.semantic_canvas.delete("all")
        self.icg_output.delete("1.0", tk.END)
        self.generate_button.configure(state="disabled")
        self.type_vars = {}

        try:
            self.tokens, symbol_table = lexer(self.code_input.get("1.0", tk.END))
            self.lexical_output.insert(tk.END, f"Tokens: {' '.join(t[1] for t in self.tokens)}\nSymbol Table: {symbol_table}")

            if symbol_table:
                ctk.CTkLabel(self.type_frame, text="Define Variable Types", font=("Segoe UI", 14, "bold")).pack(pady=5)
                row_frame = ctk.CTkFrame(self.type_frame)
                row_frame.pack()
                for var in symbol_table.keys():
                    ctk.CTkLabel(row_frame, text=f"{var}:", font=("Segoe UI", 13)).pack(side="left", padx=5)
                    self.type_vars[var] = StringVar(value='int')
                    option = ctk.CTkOptionMenu(row_frame, variable=self.type_vars[var], values=["int", "float"])
                    option.pack(side="left", padx=5)

                self.generate_button.configure(state="normal")

        except Exception as e:
            self.lexical_output.insert(tk.END, f"\nError: {e}")

    def run_parsing(self):
        self.syntax_canvas.delete("all")
        self.semantic_canvas.delete("all")
        self.icg_output.delete("1.0", tk.END)

        try:
            type_table = {var: type_var.get() for var, type_var in self.type_vars.items()}
            syntax_tree = Parser(self.tokens).parse()
            semantic_tree = Parser(self.tokens).parse()
            semantic_analysis(semantic_tree, type_table)

            width = 1000
            self.draw_tree(self.syntax_canvas, syntax_tree, width/2, 40, width/4, 70)
            self.draw_semantic_tree(self.semantic_canvas, semantic_tree, type_table, width/2, 40, width/4, 80)

            # Generate ICG
            icg_tree = Parser(self.tokens).parse()
            semantic_analysis(icg_tree, type_table)
            
            # First, collect all conversions needed (skip left side of assignment)
            conversions = {}
            temp_counter = collect_conversions(icg_tree, type_table, conversions, 1, skip_left_assign=True)
            
            # Add all conversion instructions at the start
            instructions = []
            for key, (temp_name, instruction) in sorted(conversions.items(), key=lambda x: x[1][0]):
                instructions.append(instruction)
            
            # Then generate the rest of the code
            generate_icg(icg_tree, type_table, instructions, temp_counter, conversions)
            
            # Display ICG
            icg_text = "\n".join(instructions)
            self.icg_output.insert(tk.END, icg_text)

        except Exception as e:
            self.syntax_canvas.create_text(400, 150, text=f"Error: {e}", fill="red", font=("Segoe UI", 12))
            self.icg_output.insert(tk.END, f"Error: {e}")

    def draw_tree(self, canvas, node, x, y, x_off, y_off):
        if not node: return
        canvas.create_text(x, y, text=node.value, fill="white", font=("Consolas", 12, "bold"))
        if node.left:
            canvas.create_line(x, y + 10, x - x_off, y + y_off - 10, fill="#666")
            self.draw_tree(canvas, node.left, x - x_off, y + y_off, x_off/2, y_off)
        if node.right:
            canvas.create_line(x, y + 10, x + x_off, y + y_off - 10, fill="#666")
            self.draw_tree(canvas, node.right, x + x_off, y + y_off, x_off/2, y_off)

    def draw_semantic_tree(self, canvas, node, types, x, y, x_off, y_off):
        if not node: return
        text = node.value
        if node.node_type == 'ID' and get_type(node, types) == 'float':
            text = f"{node.value} (float)"
        if node.node_type == 'NUMBER' and node.type_info == "int to float":
            text = f"{float(node.value):.1f}"
        canvas.create_text(x, y, text=text, fill="lightblue", font=("Consolas", 12, "bold"))
        if node.left:
            canvas.create_line(x, y + 10, x - x_off, y + y_off - 10, fill="#666")
            self.draw_semantic_tree(canvas, node.left, types, x - x_off, y + y_off, x_off/2, y_off)
        if node.right:
            canvas.create_line(x, y + 10, x + x_off, y + y_off - 10, fill="#666")
            self.draw_semantic_tree(canvas, node.right, types, x + x_off, y + y_off, x_off/2, y_off)


if __name__ == "__main__":
    app = CompilerGUI()
    app.mainloop()

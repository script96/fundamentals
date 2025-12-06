const API_URL = 'http://localhost:5000/api';

// DOM Elements
const codeInput = document.getElementById('code-input');
const analyzeBtn = document.getElementById('analyze-btn');
const compileBtn = document.getElementById('compile-btn');
const resetBtn = document.getElementById('reset-btn');
const typeTableSection = document.getElementById('type-table-section');
const typeInputs = document.getElementById('type-inputs');
const tokensOutput = document.getElementById('tokens-output');
const symbolTableBody = document.querySelector('#symbol-table tbody');
const syntaxTree = document.getElementById('syntax-tree');
const semanticTree = document.getElementById('semantic-tree');
const icgOutput = document.getElementById('icg-output');
const optimizedOutput = document.getElementById('optimized-output');
const assemblyOutput = document.getElementById('assembly-output');
const errorDisplay = document.getElementById('error-display');

let currentSymbolTable = {};

// Event Listeners
analyzeBtn.addEventListener('click', analyzeLexical);
compileBtn.addEventListener('click', compile);
resetBtn.addEventListener('click', reset);
codeInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') analyzeLexical();
});

// Analyze lexical (first step)
async function analyzeLexical() {
    const code = codeInput.value.trim();
    if (!code) {
        showError('Please enter some code to analyze.');
        return;
    }

    hideError();
    clearOutputs();

    try {
        const response = await fetch(`${API_URL}/lexical`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ code })
        });

        const data = await response.json();

        if (!data.success) {
            showError(data.detail || data.error || 'Analysis failed');
            return;
        }

        // Display tokens
        displayTokens(data.tokens);

        // Display symbol table
        displaySymbolTable(data.symbol_table);

        // Store symbol table and show type inputs
        currentSymbolTable = data.symbol_table;
        showTypeInputs(data.symbol_table);

        // Enable compile button
        compileBtn.disabled = false;

    } catch (error) {
        showError(`Error connecting to API: ${error.message}`);
    }
}

// Full compilation
async function compile() {
    const code = codeInput.value.trim();
    const typeTable = getTypeTable();

    hideError();

    try {
        const response = await fetch(`${API_URL}/compile`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ code, type_table: typeTable })
        });

        const data = await response.json();

        if (!data.success) {
            showError(data.detail || data.error || 'Compilation failed');
            return;
        }

        // Display all phases
        displayTokens(data.lexical.tokens);
        displaySymbolTable(data.lexical.symbol_table);
        displaySyntaxTree(data.syntax_tree);
        displaySemanticTree(data.semantic_tree);
        displayICG(data.intermediate_code);
        displayOptimized(data.optimized_code);
        displayAssembly(data.assembly_code);

    } catch (error) {
        showError(`Error connecting to API: ${error.message}`);
    }
}

// Display functions
function displayTokens(tokens) {
    tokensOutput.innerHTML = tokens.map(t => 
        `<span class="token ${t.type}">${t.original}</span>`
    ).join('');
}

function displaySymbolTable(symbolTable) {
    symbolTableBody.innerHTML = Object.entries(symbolTable).map(([name, id]) =>
        `<tr><td>${name}</td><td>${id}</td></tr>`
    ).join('');
}

function showTypeInputs(symbolTable) {
    const variables = Object.keys(symbolTable);
    
    // Get the first variable (the one being assigned to) - it shouldn't have a type selector
    const code = codeInput.value.trim();
    const assignedVar = code.split('=')[0].trim();
    
    // Filter out the assigned variable
    const inputVariables = variables.filter(v => v !== assignedVar);
    
    if (inputVariables.length === 0) {
        typeTableSection.style.display = 'none';
        return;
    }

    typeInputs.innerHTML = inputVariables.map(varName => `
        <div class="type-input-group">
            <label>${varName}:</label>
            <select id="type-${varName}">
                <option value="int">int</option>
                <option value="float">float</option>
            </select>
        </div>
    `).join('');

    typeTableSection.style.display = 'block';
}

function getTypeTable() {
    const typeTable = {};
    for (const varName of Object.keys(currentSymbolTable)) {
        const select = document.getElementById(`type-${varName}`);
        if (select) {
            typeTable[varName] = select.value;
        }
    }
    return typeTable;
}

function displaySyntaxTree(tree) {
    syntaxTree.innerHTML = buildTreeHTML(tree, false);
    // Draw lines after a small delay to ensure DOM is rendered
    setTimeout(() => drawTreeLines(syntaxTree), 50);
}

function displaySemanticTree(tree) {
    semanticTree.innerHTML = buildTreeHTML(tree, true);
    setTimeout(() => drawTreeLines(semanticTree), 50);
}

function buildTreeHTML(node, showCoercion = false) {
    if (!node) return '';

    let nodeClass = 'tree-node-value';
    let displayValue = node.value;

    // Determine node styling
    if (node.node_type === 'OP' || node.node_type === 'ASSIGN') {
        nodeClass += ' operator';
    } else if (node.node_type === 'ID') {
        nodeClass += ' id';
        if (node.original_name) {
            displayValue = node.original_name;
        }
    } else if (node.node_type === 'NUMBER') {
        nodeClass += ' number';
    }

    // Add coercion indicator for semantic tree
    if (showCoercion && node.type_info === 'int to float') {
        nodeClass += ' coerced';
        displayValue += ' →float';
    }

    let html = `<div class="tree-node">`;
    html += `<div class="${nodeClass}">${displayValue}</div>`;

    if (node.left || node.right) {
        html += `<div class="tree-children">`;
        if (node.left) {
            html += `<div class="tree-child">${buildTreeHTML(node.left, showCoercion)}</div>`;
        }
        if (node.right) {
            html += `<div class="tree-child">${buildTreeHTML(node.right, showCoercion)}</div>`;
        }
        html += `</div>`;
    }

    html += `</div>`;
    return html;
}

function drawTreeLines(container) {
    // Remove existing SVG if any
    const existingSvg = container.querySelector('.tree-svg');
    if (existingSvg) existingSvg.remove();

    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.classList.add('tree-svg');
    
    const containerRect = container.getBoundingClientRect();
    svg.setAttribute('width', container.scrollWidth);
    svg.setAttribute('height', container.scrollHeight);
    
    // Find all parent nodes with children
    const nodes = container.querySelectorAll('.tree-node');
    
    nodes.forEach(node => {
        const parentValue = node.querySelector(':scope > .tree-node-value');
        const childrenContainer = node.querySelector(':scope > .tree-children');
        
        if (parentValue && childrenContainer) {
            const children = childrenContainer.querySelectorAll(':scope > .tree-child > .tree-node > .tree-node-value');
            
            const parentRect = parentValue.getBoundingClientRect();
            const parentX = parentRect.left + parentRect.width / 2 - containerRect.left;
            const parentY = parentRect.bottom - containerRect.top;
            
            children.forEach(child => {
                const childRect = child.getBoundingClientRect();
                const childX = childRect.left + childRect.width / 2 - containerRect.left;
                const childY = childRect.top - containerRect.top;
                
                const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
                line.setAttribute('x1', parentX);
                line.setAttribute('y1', parentY);
                line.setAttribute('x2', childX);
                line.setAttribute('y2', childY);
                svg.appendChild(line);
            });
        }
    });
    
    container.insertBefore(svg, container.firstChild);
}

function displayICG(instructions) {
    icgOutput.textContent = instructions.join('\n');
}

function displayOptimized(instructions) {
    optimizedOutput.textContent = instructions.join('\n');
}

function displayAssembly(instructions) {
    assemblyOutput.textContent = instructions.join('\n');
}

// Utility functions
function showError(message) {
    errorDisplay.textContent = `❌ Error: ${message}`;
    errorDisplay.style.display = 'block';
}

function hideError() {
    errorDisplay.style.display = 'none';
}

function clearOutputs() {
    tokensOutput.innerHTML = '<span style="color:#666;">Click "Analyze Code" to see tokens...</span>';
    symbolTableBody.innerHTML = '';
    syntaxTree.innerHTML = '<span style="color:#666;">Compile to see parse tree...</span>';
    semanticTree.innerHTML = '<span style="color:#666;">Compile to see semantic tree...</span>';
    icgOutput.textContent = 'Compile to see intermediate code...';
    optimizedOutput.textContent = 'Compile to see optimized code...';
    assemblyOutput.textContent = 'Compile to see assembly code...';
}

function reset() {
    codeInput.value = '';
    currentSymbolTable = {};
    typeTableSection.style.display = 'none';
    typeInputs.innerHTML = '';
    compileBtn.disabled = true;
    clearOutputs();
    hideError();
}

// Initial state
clearOutputs();

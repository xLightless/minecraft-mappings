"""
This script parses a ProGuard/R8 style mapping file and generates a full
Java source tree, with each class in its own file, mirroring the original
package structure.

This approach is highly idiomatic for Java, ensures maximum IDE performance,
and produces a clean, navigable codebase. It correctly handles invalid Java
identifiers (e.g., with hyphens, starting with digits, or matching keywords)
and inner classes.
"""

import os
import re
import sys
import shutil
from collections import defaultdict

# --- CONFIGURATION ---
# The script will attempt to download this file if it's not found locally.
MOJANG_URL = "https://piston-data.mojang.com/v1/objects/94d453080a58875d3acc1a9a249809767c91ed40/server.txt"
INPUT_FILENAME = "server.txt"
# The root directory where the generated package structure will be created.
# This should point to the source directory of your Maven/Gradle project, e.g., "my-library/src/main/java"
OUTPUT_DIRECTORY = "mappings-1.21.6"
# Define a base package for the generated Java files.
# All generated files will be placed under this package.
# Example: `net.minecraft.block.Block` becomes `com.mycompany.mappings.net.minecraft.block.Block`.
BASE_PACKAGE_NAME = "com.reeceturner.mappings"


# --- Setup ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_FILE = os.path.join(SCRIPT_DIR, INPUT_FILENAME)
OUTPUT_ROOT_DIR = os.path.join(SCRIPT_DIR, OUTPUT_DIRECTORY)

# A set of all Java keywords for fast lookups.
JAVA_KEYWORDS = {
    "abstract", "continue", "for", "new", "switch", "assert", "default",
    "goto", "package", "synchronized", "boolean", "do", "if", "private",
    "this", "break", "double", "implements", "protected", "throw", "byte",
    "else", "import", "public", "throws", "case", "enum", "instanceof",
    "return", "transient", "catch", "extends", "int", "short", "try",
    "char", "final", "interface", "static", "void", "class", "finally",
    "long", "strictfp", "volatile", "const", "float", "native", "super",
    "while", "true", "false", "null"
}


def to_java_identifier(name):
    """
    Converts a string into a valid Java identifier.
    - Replaces invalid characters with underscores.
    - Prefixes with an underscore if it starts with a digit.
    - Suffixes with an underscore if it is a Java keyword.
    """
    # Suffix a keyword with an underscore.
    if name in JAVA_KEYWORDS:
        return f"{name}_"

    # Replace all non-alphanumeric characters (except _) with an underscore.
    sanitized = re.sub(r'[^a-zA-Z0-9_]', '_', name)

    # Prefix with an underscore if the name starts with a digit.
    if sanitized and sanitized[0].isdigit():
        sanitized = "_" + sanitized

    # Handle cases where the name becomes empty after sanitization (e.g. "-")
    if not sanitized:
        return "_"

    return sanitized


def to_java_constant_name(name):
    """
    Converts a field or method name to a valid Java constant name
    (UPPER_SNAKE_CASE).
    """
    if name == "<init>": return "INIT"
    if name == "<clinit>": return "CLINIT"

    name = re.sub(r'(?<=[a-z0-9])([A-Z])', r'_\1', name)
    name = re.sub(r'(?<=[A-Z])([A-Z][a-z])', r'_\1', name)
    name = re.sub(r'[^a-zA-Z0-9_]', '_', name)

    upper_name = name.upper()

    # A constant is an identifier, so it also can't start with a number.
    if upper_name and upper_name[0].isdigit():
        upper_name = "_" + upper_name

    return upper_name


def get_method_params_suffix(signature):
    """
    Creates a suffix string from a method's parameters for disambiguation.
    """
    match = re.search(r'\((.*)\)', signature)
    if not match or not match.group(1): return ""

    params = match.group(1).split(',')
    sanitized_parts = []
    for p_type in params:
        simple_type = p_type.strip().split('.')[-1]
        simple_type = simple_type.replace('[]', '_ARRAY').replace('<', '_').replace('>', '')
        sanitized_parts.append(to_java_constant_name(simple_type))
    return "_" + "_".join(filter(None, sanitized_parts))


def main():
    """Main execution function."""
    if not os.path.exists(INPUT_FILE):
        print(f"Input file '{INPUT_FILENAME}' not found.")
        try:
            import urllib.request
            print(f"Attempting to download from {MOJANG_URL}...")
            urllib.request.urlretrieve(MOJANG_URL, INPUT_FILE)
            print("Download successful.")
        except Exception as e:
            sys.exit(f"Error: Download failed: {e}. Please manually place the file at '{INPUT_FILE}'")

    mappings = defaultdict(lambda: {'obf': '', 'fields': [], 'methods': []})
    current_class_name = None
    method_re = re.compile(r"(\S+)\s*\(")
    line_number_re = re.compile(r"^\d+:\d+:")

    print(f"Reading and parsing mappings from '{INPUT_FILENAME}'...")
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        for line in f:
            stripped_line = line.strip()
            if not stripped_line or stripped_line.startswith("#"): continue
            if stripped_line.endswith(":"):
                parts = stripped_line.rstrip(":").split(" -> ")
                if len(parts) == 2:
                    current_class_name = parts[0]
                    mappings[current_class_name]['obf'] = parts[1]
                continue
            if line.startswith("    ") and " -> " in line and current_class_name:
                member_line, obf_name = stripped_line.split(" -> ", 1)
                definition_part = member_line.strip()
                if "(" in definition_part:
                    match = method_re.search(definition_part)
                    if match:
                        method_name = match.group(1).split('.')[-1]
                        full_signature = line_number_re.sub('', definition_part)
                        mappings[current_class_name]['methods'].append({
                            'obf': obf_name, 'named': method_name, 'signature': full_signature
                        })
                else:
                    field_name = definition_part.rsplit(' ', 1)[-1]
                    mappings[current_class_name]['fields'].append({'obf': obf_name, 'named': field_name})

    print("Parsing complete. Generating Java source files...")
    if os.path.exists(OUTPUT_ROOT_DIR):
        print(f"Cleaning previous output directory: '{OUTPUT_ROOT_DIR}'")
        shutil.rmtree(OUTPUT_ROOT_DIR)

    file_count = 0
    for original_name, info in sorted(mappings.items()):
        # --- Sanitize package and class names ---
        name_with_underscores = original_name.replace('$', '_')
        raw_parts = name_with_underscores.split('.')
        sanitized_parts = [to_java_identifier(part) for part in raw_parts]
        simple_class_name = sanitized_parts[-1]
        package_parts = sanitized_parts[:-1]
        full_package_parts = [p for p in BASE_PACKAGE_NAME.split('.') if p] + package_parts
        full_package_name = ".".join(full_package_parts)

        # --- Create directory structure ---
        output_dir_for_class = os.path.join(OUTPUT_ROOT_DIR, *full_package_parts)
        os.makedirs(output_dir_for_class, exist_ok=True)

        # --- Generate Java file content ---
        java_lines = []
        if full_package_name:
            java_lines.append(f"package {full_package_name};\n")

        java_lines.extend([
            "/**",
            f" * Mappings for the {{@code {original_name}}} class.",
            " * This file is automatically generated. Do not edit.",
            " */",
            f"public final class {simple_class_name} {{",
            f"    private {simple_class_name}() {{}}",
            "",
            f'    public static final String ORIGINAL_NAME = "{original_name}";'
        ])

        if info['obf']:
            java_lines.append(f'    public static final String OBFUSCATED_NAME = "{info["obf"]}";')

        # Generate Fields sub-class
        if info['fields']:
            java_lines.append("\n    public static final class Fields {")
            java_lines.append("        private Fields() {}")
            # --- MODIFICATION START: Handle duplicate field names ---
            declared_fields = set()
            for field in sorted(info['fields'], key=lambda x: x['named']):
                base_const_name = to_java_constant_name(field['named'])
                if not base_const_name:
                    continue

                const_name = base_const_name
                counter = 2
                while const_name in declared_fields:
                    const_name = f"{base_const_name}_{counter}"
                    counter += 1

                java_lines.append(f'        public static final String {const_name} = "{field["obf"]}";')
                declared_fields.add(const_name)
            # --- MODIFICATION END ---
            java_lines.append("    }")

        # Generate Methods sub-class
        if info['methods']:
            java_lines.append("\n    public static final class Methods {")
            java_lines.append("        private Methods() {}")
            # --- MODIFICATION START: Handle duplicate method names ---
            declared_methods = set()
            for method in sorted(info['methods'], key=lambda x: (x['named'], x['signature'])):
                const_name_base = to_java_constant_name(method['named'])
                if not const_name_base:
                    continue

                suffix = get_method_params_suffix(method['signature'])
                base_const_name = f"{const_name_base}{suffix}"

                const_name = base_const_name
                counter = 2
                while const_name in declared_methods:
                    const_name = f"{base_const_name}_{counter}"
                    counter += 1

                java_lines.append(f'        public static final String {const_name} = "{method["obf"]}";')
                declared_methods.add(const_name)
            # --- MODIFICATION END ---
            java_lines.append("    }")

        java_lines.append("}")

        # --- Write the file ---
        output_file_path = os.path.join(output_dir_for_class, f"{simple_class_name}.java")
        with open(output_file_path, "w", encoding="utf-8") as f:
            f.write("\n".join(java_lines))
        file_count += 1

    print(f"\nDone! Generated {file_count} Java files in '{OUTPUT_DIRECTORY}'.")


if __name__ == "__main__":
    main()
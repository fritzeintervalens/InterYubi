"""Double-click this file to start InterYubi (no console window).

On Windows, .pyw files are run by pythonw.exe automatically,
so no console window will appear.
"""
import os
import sys

# Ensure imports resolve relative to this file's directory
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.getcwd())

from interyubi import main

main()

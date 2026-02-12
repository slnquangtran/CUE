#!/usr/bin/env python3
import os
import sys

def main():
    root = os.path.abspath(os.getcwd())
    nested = []
    for dirpath, dirnames, filenames in os.walk(root):
        # check for other directories named 'CUE' beyond the repo root
        for name in dirnames:
            if name == 'CUE':
                full = os.path.abspath(os.path.join(dirpath, name))
                if os.path.normpath(full) != os.path.normpath(root):
                    nested.append(full)
    if nested:
        print("Found nested CUE directories (more than one):")
        for p in nested:
            print(" -", p)
        sys.exit(1)
    print("OK: No nested CUE directories found.")
    sys.exit(0)

if __name__ == '__main__':
    main()

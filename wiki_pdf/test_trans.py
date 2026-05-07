import sys
import traceback
from googletrans import Translator
with open("test_trans.log", "w") as f:
    try:
        f.write("Starting...\n")
        translator = Translator()
        f.write("Translator initialized.\n")
        res = translator.translate('hello', dest='kn')
        f.write(f"Result: {res.text}\n")
    except Exception as e:
        f.write(f"Error: {str(e)}\n")
        f.write(traceback.format_exc())

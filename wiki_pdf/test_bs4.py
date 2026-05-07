from bs4 import BeautifulSoup
html = "<table><tr><td>Hello <b>World</b></td></tr></table>"
soup = BeautifulSoup(html, "html.parser")
texts = []
nodes = []
for node in soup.find_all(string=True):
    if node.strip():
        texts.append(node)
        nodes.append(node)
        
texts[0].replace_with("Hola ")
texts[1].replace_with("Mundo")
print(str(soup))

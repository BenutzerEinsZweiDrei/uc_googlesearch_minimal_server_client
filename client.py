# client.py

from minimal_server import MinimalClient

# WICHTIG: Dummy-Klasse mit denselben Methodennamen wie auf dem Server
class GetResults:
    def __init__(self):
        pass

    def open_google(self):
        pass

    def accept_cookies(self):
        pass

    def search_query(self, query="zumba"):
        pass

    def extract_results(self):
        pass

    def run(self):
        pass
        
if __name__ == "__main__":
    proxy = MinimalClient(GetResults, host="localhost", port=4444)

    tab = proxy.run()
    for i in tab:
        print(i)
        print("--")
    
    print("Press Enter to continue..")
    input()
    
    tab = proxy.run()
    for i in tab:
        print(i)
        print("--")
    


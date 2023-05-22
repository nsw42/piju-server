class DownloadHistory:
    def __init__(self, max_length=10):
        self.entries = []  # The actual downloaded URLs
        self.files = {}  # URL -> List[DownloadInfo]
        self.max_length = max_length

    def add(self, url):
        if url in self.entries:
            index = self.entries.index(url)
            self.entries.pop(index)
        self.entries.insert(0, url)
        self.entries = self.entries[:self.max_length]

    def set_info(self, url, files):
        self.files[url] = files

    def get_info(self, url):
        return self.files.get(url)

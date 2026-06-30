from abc import ABC, abstractmethod


class PcdnAdapter(ABC):
    provider_name = ""

    @abstractmethod
    def list_resources(self):
        raise NotImplementedError

    @abstractmethod
    def create_task(self, task):
        raise NotImplementedError

    @abstractmethod
    def get_task(self, task_id):
        raise NotImplementedError

    @abstractmethod
    def sync_usage(self, since=None, until=None):
        raise NotImplementedError

    @abstractmethod
    def health(self):
        raise NotImplementedError

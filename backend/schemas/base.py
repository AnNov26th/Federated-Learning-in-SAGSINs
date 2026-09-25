from typing import TypeVar, Generic, Optional, Any
from pydantic import BaseModel

T = TypeVar('T')

class APIResponse(BaseModel, Generic[T]):
    status: str = 'success'
    message: Optional[str] = None
    data: Optional[T] = None

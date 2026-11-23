"""컬렉션 API — 목록/CRUD/파일/쉐어포인트 링크 + 파일 본문(미리보기).

응답은 chats API와 같은 평문 JSON. 채팅 연동 자체는 chats_api(stream)가 chats.coll 태그로 처리한다.
"""
# Collections API — list/CRUD/files/SharePoint links + file body (preview).
# Plain JSON like the chats API. The chat linkage itself is handled by chats_api (stream) via chats.coll.

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import collections_store as store

router = APIRouter(prefix="/api/collections")


class CollCreate(BaseModel):
    name: str
    description: str = ""
    inst: str = ""
    summary: str = ""


class CollPatch(BaseModel):
    name: str | None = None
    summary: str | None = None
    description: str | None = None
    inst: str | None = None
    pinned: bool | None = None


class FileCreate(BaseModel):
    name: str
    content: str = ""


class LinkBody(BaseModel):
    url: str


@router.get("")
def list_collections() -> list[dict]:
    return store.list_collections()


@router.post("")
def create_collection(body: CollCreate) -> dict:
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="name이 비어 있습니다")
    return store.create_collection(name, body.description.strip(), body.inst.strip(), body.summary.strip())


@router.patch("/{coll_id}")
def patch_collection(coll_id: str, body: CollPatch) -> dict:
    patch = body.model_dump(exclude_unset=True)
    if "name" in patch and not (patch["name"] or "").strip():
        raise HTTPException(status_code=422, detail="name이 비어 있습니다")
    if not store.update_collection(coll_id, patch):
        raise HTTPException(status_code=404, detail="존재하지 않는 컬렉션입니다")
    return {"ok": True}


@router.delete("/{coll_id}")
def delete_collection(coll_id: str) -> dict:
    if not store.delete_collection(coll_id):
        raise HTTPException(status_code=404, detail="존재하지 않는 컬렉션입니다")
    return {"ok": True}


@router.get("/{coll_id}/files/{file_id}")
def get_file(coll_id: str, file_id: str) -> dict:
    f = store.get_file(coll_id, file_id)
    if f is None:
        raise HTTPException(status_code=404, detail="존재하지 않는 파일입니다")
    return f


@router.post("/{coll_id}/files")
def add_file(coll_id: str, body: FileCreate) -> dict:
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="name이 비어 있습니다")
    f = store.add_file(coll_id, name, body.content)
    if f is None:
        raise HTTPException(status_code=404, detail="존재하지 않는 컬렉션입니다")
    return f


@router.delete("/{coll_id}/files/{file_id}")
def remove_file(coll_id: str, file_id: str) -> dict:
    if not store.remove_file(coll_id, file_id):
        raise HTTPException(status_code=404, detail="존재하지 않는 파일입니다")
    return {"ok": True}


@router.post("/{coll_id}/links")
def add_link(coll_id: str, body: LinkBody) -> dict:
    url = body.url.strip()
    if not url:
        raise HTTPException(status_code=422, detail="url이 비어 있습니다")
    l = store.add_link(coll_id, url)
    if l is None:
        raise HTTPException(status_code=404, detail="존재하지 않는 컬렉션입니다")
    return l


@router.patch("/{coll_id}/links/{link_id}")
def patch_link(coll_id: str, link_id: str, body: LinkBody) -> dict:
    url = body.url.strip()
    if not url:
        raise HTTPException(status_code=422, detail="url이 비어 있습니다")
    if not store.update_link(coll_id, link_id, url):
        raise HTTPException(status_code=404, detail="존재하지 않는 링크입니다")
    return {"ok": True}


@router.delete("/{coll_id}/links/{link_id}")
def remove_link(coll_id: str, link_id: str) -> dict:
    if not store.remove_link(coll_id, link_id):
        raise HTTPException(status_code=404, detail="존재하지 않는 링크입니다")
    return {"ok": True}

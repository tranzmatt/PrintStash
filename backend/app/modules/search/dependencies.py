"""Bounded extraction inventory, separate from read-time access dependencies."""

from printstash_core.search.passages import MAX_FIELD_ITEMS, SearchSubject, SubjectType
from sqlmodel import Session, col, select

from app.db.models import (
    Collection,
    Document,
    File,
    Model,
    ModelProvenanceSource,
    MultipartModel,
    MultipartModelChoice,
    Tag,
)
from app.db.projections import ContentSource
from app.db.scopes import live
from app.modules.library.library_search import effective_tag_pairs

SUBJECT_MODELS = {
    SubjectType.MODEL: Model,
    SubjectType.COLLECTION: Collection,
    SubjectType.DOCUMENT: Document,
    SubjectType.MULTIPART_MODEL: MultipartModel,
}


def _collection_chain(session: Session, collection_id: int) -> set[int]:
    """``collection_id`` and every parent above it, in one statement.

    Every parent a row names counts, existing or not, and a cycle stops at its
    first repeat: UNION, not UNION ALL, discards a row already visited.
    """
    chain = (
        select(col(Collection.id), col(Collection.parent_id))
        .where(col(Collection.id) == collection_id)
        .cte("collection_chain", recursive=True)
    )
    chain = chain.union(
        select(col(Collection.id), col(Collection.parent_id)).join(
            chain, col(Collection.id) == chain.c.parent_id
        )
    )
    ids = {collection_id}
    for _id, parent_id in session.execute(
        select(chain.c.id, chain.c.parent_id)
    ).tuples():
        if parent_id is not None:
            ids.add(parent_id)
    return ids


def extraction_dependencies(
    session: Session, subject: SearchSubject
) -> set[ContentSource]:
    row = session.get(SUBJECT_MODELS[subject.subject_type], subject.subject_id)
    if row is None:
        return set()
    refs = {ContentSource(subject.subject_type.value, subject.subject_id)}
    collection_id = row.id if isinstance(row, Collection) else row.collection_id
    if collection_id is not None:
        refs.update(
            ContentSource("collection", ancestor)
            for ancestor in _collection_chain(session, collection_id)
        )
    if isinstance(row, Model):
        files = session.exec(
            select(File.id)
            .where(File.model_id == row.id, live(File))
            .order_by(File.version, File.id)
            .limit(MAX_FIELD_ITEMS + 1)
        ).all()
        sources = session.exec(
            select(ModelProvenanceSource.id)
            .where(ModelProvenanceSource.model_id == row.id)
            .order_by(ModelProvenanceSource.id)
            .limit(MAX_FIELD_ITEMS + 1)
        ).all()
        pairs = effective_tag_pairs().subquery()
        tags = session.exec(
            select(Tag.id)
            .where(Tag.id.in_(select(pairs.c.tag_id).where(pairs.c.model_id == row.id)))
            .order_by(Tag.name, Tag.id)
            .limit(MAX_FIELD_ITEMS + 1)
        ).all()
        for kind, ids in (("file", files), ("provenance", sources), ("tag", tags)):
            refs.update(ContentSource(kind, id) for id in ids if id is not None)
    if isinstance(row, MultipartModel):
        members = session.exec(
            select(MultipartModelChoice.model_id)
            .where(MultipartModelChoice.multipart_model_id == row.id)
            .order_by(
                MultipartModelChoice.multipart_part_id,
                MultipartModelChoice.sort_order,
                MultipartModelChoice.id,
            )
            .limit(MAX_FIELD_ITEMS + 1)
        ).all()
        refs.update(ContentSource("model", id) for id in members)
    return refs

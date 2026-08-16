import pytest
import os
from datetime import datetime, timezone
from sqlalchemy.exc import IntegrityError
from src.models import db, User, FavoriteTeam, FavoritePlayer



def test_user_creation_and_uuidv7(isolated_db):
    user = User(
        email="test@example.com",
        password_hash="fakehash",
        first_name="Test",
        last_name="User"
    )
    isolated_db.session.add(user)
    isolated_db.session.commit()

    assert user.id is not None
    # Check if UUIDv7 (version 7)
    assert user.id.version == 7
    
    # Check UTC timestamps
    assert user.created_at is not None
    if user.created_at.tzinfo is not None:
        assert user.created_at.tzinfo == timezone.utc
    assert user.updated_at is not None
    if user.updated_at.tzinfo is not None:
        assert user.updated_at.tzinfo == timezone.utc

def test_postgres_uuid_and_timezone(postgres_db):
    user = User(
        email="pgtest@example.com",
        password_hash="fakehash",
        first_name="Test",
        last_name="User"
    )
    postgres_db.session.add(user)
    postgres_db.session.commit()

    assert user.id is not None
    assert user.id.version == 7
    
    # Postgres guarantees tzinfo is returned when timezone=True
    assert user.created_at.tzinfo == timezone.utc
    assert user.updated_at.tzinfo == timezone.utc

def test_email_normalization(isolated_db):
    user1 = User(
        email=User.normalize_email("  Test.One@EXAMPLE.com  "),
        password_hash="fakehash",
        first_name="Test1",
        last_name="User"
    )
    isolated_db.session.add(user1)
    isolated_db.session.commit()
    
    assert user1.email == "test.one@example.com"

    # Duplicate normalized email should fail
    user2 = User(
        email=User.normalize_email("test.one@example.com"),
        password_hash="fakehash2",
        first_name="Test2",
        last_name="User"
    )
    isolated_db.session.add(user2)
    with pytest.raises(IntegrityError):
        isolated_db.session.commit()
    isolated_db.session.rollback()

def test_favorite_team_uniqueness(isolated_db):
    user = User(email="fav@example.com", password_hash="h", first_name="A", last_name="B")
    isolated_db.session.add(user)
    isolated_db.session.commit()

    fav1 = FavoriteTeam(user_id=user.id, team_id=123)
    isolated_db.session.add(fav1)
    isolated_db.session.commit()

    # Adding the same team again should raise IntegrityError
    fav2 = FavoriteTeam(user_id=user.id, team_id=123)
    isolated_db.session.add(fav2)
    with pytest.raises(IntegrityError):
        isolated_db.session.commit()
    isolated_db.session.rollback()

def test_cascade_delete(isolated_db):
    user = User(email="cascade@example.com", password_hash="h", first_name="A", last_name="B")
    isolated_db.session.add(user)
    isolated_db.session.commit()
    
    uid = user.id

    fav_t = FavoriteTeam(user_id=uid, team_id=123)
    fav_p = FavoritePlayer(user_id=uid, player_id=456)
    isolated_db.session.add_all([fav_t, fav_p])
    isolated_db.session.commit()

    assert FavoriteTeam.query.count() == 1
    assert FavoritePlayer.query.count() == 1

    # Delete user
    isolated_db.session.delete(user)
    isolated_db.session.commit()

    # Favorites should be cascaded
    assert FavoriteTeam.query.count() == 0
    assert FavoritePlayer.query.count() == 0

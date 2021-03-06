# coding=utf-8
import hashlib
import os
import time
from django.utils.timezone import now
from alert.lib.solr_core_admin import create_solr_core, delete_solr_core, swap_solr_core
from alert.lib.string_utils import trunc
from alert.lib import sunburnt
from alert.scrapers.DupChecker import DupChecker
from alert.scrapers.models import urlToHash
from alert.scrapers.management.commands.cl_scrape_and_extract import get_extension
from alert.scrapers.management.commands.cl_scrape_and_extract import scrape_court
from alert.scrapers.tasks import extract_from_txt
from alert.scrapers.test_assets import test_scraper
from alert.search.models import Citation, Court, Document
from alert import settings
from celery.task.sets import subtask
from datetime import date, timedelta
from django.core.files.base import ContentFile
from django.test import TestCase
from scrapers.tasks import extract_doc_content
from scrapers.tasks import extract_by_ocr


class IngestionTest(TestCase):
    fixtures = ['test_court.json']

    def ingest_documents(self):
        site = test_scraper.Site().parse()
        scrape_court(site)

    def setUp(self):
        # Set up a testing core in Solr and swap it in
        self.core_name = '%s.test-%s' % (self.__module__, time.time())
        create_solr_core(self.core_name)
        swap_solr_core('collection1', self.core_name)
        self.si = sunburnt.SolrInterface(settings.SOLR_URL, mode='rw')

        # Set up a handy court object
        self.court = Court.objects.get(pk='test')

    def tearDown(self):
        swap_solr_core(self.core_name, 'collection1')
        delete_solr_core(self.core_name)

    def test_parsing_xml_document_to_site_object(self):
        """Does a basic parse of a site reveal the right number of items?"""
        site = test_scraper.Site().parse()
        self.assertEqual(len(site.case_names), 6)

    def test_content_extraction(self):
        """Do all of the supported mimetypes get extracted to text successfully, including OCR?"""
        site = test_scraper.Site().parse()

        test_strings = ['supreme',
                        'intelligence',
                        'indiana',
                        'reagan',
                        'indiana',
                        'fidelity']
        for i in range(0, len(site.case_names)):
            path = os.path.join(settings.INSTALL_ROOT, 'alert', site.download_urls[i])
            with open(path) as f:
                content = f.read()
                cf = ContentFile(content)
                extension = get_extension(content)
            cite = Citation(case_name=site.case_names[i])
            cite.save(index=False)
            doc = Document(date_filed=site.case_dates[i],
                           court=self.court,
                           citation=cite)
            file_name = trunc(site.case_names[i].lower(), 75) + extension
            doc.local_path.save(file_name, cf, save=False)
            doc.save(index=False)
            doc = extract_doc_content(doc.pk, callback=subtask(extract_by_ocr))
            if extension in ['.html', '.wpd']:
                self.assertIn(test_strings[i], doc.html.lower())
            else:
                self.assertIn(test_strings[i], doc.plain_text.lower())

            doc.delete()

    def test_solr_ingestion_and_deletion(self):
        """Do items get added to the Solr index when they are ingested?"""
        site = test_scraper.Site().parse()
        path = os.path.join(settings.INSTALL_ROOT, 'alert', site.download_urls[0])  # a simple PDF
        with open(path) as f:
            content = f.read()
            cf = ContentFile(content)
            extension = get_extension(content)
        cite = Citation(case_name=site.case_names[0])
        cite.save(index=False)
        doc = Document(date_filed=site.case_dates[0],
                       court=self.court,
                       citation=cite)
        file_name = trunc(site.case_names[0].lower(), 75) + extension
        doc.local_path.save(file_name, cf, save=False)
        doc.save(index=False)
        extract_doc_content(doc.pk, callback=subtask(extract_by_ocr))
        response = self.si.raw_query(**{'q': 'supreme', 'caller': 'scraper_test',}).execute()
        count = response.result.numFound
        self.assertEqual(count, 1, "There were %s items found when there should have been 1" % count)


class ExtractionTest(TestCase):
    def test_txt_extraction_with_bad_data(self):
        """Verifies that we can extract text from nasty files lacking encodings."""
        path = os.path.join(settings.INSTALL_ROOT, 'alert', 'scrapers', 'test_assets', 'txt_file_with_no_encoding.txt')
        content, err = extract_from_txt(path)
        self.assertFalse(err, "Error reported while extracting text from %s" % path)
        self.assertIn(u'¶  1.  DOOLEY, J.   Plaintiffs', content,
                      "Issue extracting/encoding text from file at: %s" % path)


class DupcheckerTest(TestCase):
    fixtures = ['test_court.json']

    def setUp(self):
        self.court = Court.objects.get(pk='test')
        self.dup_checkers = [DupChecker(self.court, full_crawl=True),
                             DupChecker(self.court, full_crawl=False)]

    def test_abort_when_new_court_website(self):
        """Tests what happens when a new website is discovered."""
        site = test_scraper.Site()
        site.hash = 'this is a dummy hash code string'

        for dup_checker in self.dup_checkers:
            abort = dup_checker.abort_by_url_hash(site.url, site.hash)
            if dup_checker.full_crawl:
                self.assertFalse(abort, "DupChecker says to abort during a full crawl.")
            else:
                self.assertFalse(abort, "DupChecker says to abort on a court that's never been crawled before.")

            # The checking function creates url2Hashes, that we must delete as part of cleanup.
            dup_checker.url2Hash.delete()

    def test_abort_on_unchanged_court_website(self):
        """Similar to the above, but we create a url2hash object before checking if it exists."""
        site = test_scraper.Site()
        site.hash = 'this is a dummy hash code string'
        for dup_checker in self.dup_checkers:
            urlToHash(url=site.url, SHA1=site.hash).save()
            abort = dup_checker.abort_by_url_hash(site.url, site.hash)
            if dup_checker.full_crawl:
                self.assertFalse(abort, "DupChecker says to abort during a full crawl.")
            else:
                self.assertTrue(abort,
                                "DupChecker says not to abort on a court that's been crawled before with the same hash")

            dup_checker.url2Hash.delete()

    def test_abort_on_changed_court_website(self):
        """Similar to the above, but we create a url2Hash with a different hash before checking if it exists."""
        site = test_scraper.Site()
        site.hash = 'this is a dummy hash code string'
        for dup_checker in self.dup_checkers:
            urlToHash(url=site.url, SHA1=site.hash).save()
            abort = dup_checker.abort_by_url_hash(site.url, "this is a *different* hash!")
            if dup_checker.full_crawl:
                self.assertFalse(abort, "DupChecker says to abort during a full crawl.")
            else:
                self.assertFalse(abort, "DupChecker says to abort on a court where the hash has changed.")

            dup_checker.url2Hash.delete()

    def test_should_we_continue_break_or_carry_on_with_an_empty_database(self):
        for dup_checker in self.dup_checkers:
            onwards = dup_checker.should_we_continue_break_or_carry_on(now(),
                                                                       now() - timedelta(days=1),
                                                                       lookup_value='content',
                                                                       lookup_by='sha1')
            if not dup_checker.full_crawl:
                self.assertTrue(onwards, "DupChecker says to abort during a full crawl.")
            else:
                count = Document.objects.all().count()
                self.assertTrue(onwards, "DupChecker says to abort on dups when the database has %s Documents." % count)

    def test_should_we_continue_break_or_carry_on_with_a_dup_found(self):
        # Set the dup_threshold to zero for this test
        self.dup_checkers = [DupChecker(self.court, full_crawl=True, dup_threshold=0),
                             DupChecker(self.court, full_crawl=False, dup_threshold=0)]
        content = "this is dummy content that we hash"
        content_hash = hashlib.sha1(content).hexdigest()
        for dup_checker in self.dup_checkers:
            # Create a document, then use the dup_cheker to see if it exists.
            doc = Document(sha1=content_hash, court=self.court)
            doc.save(index=False)
            onwards = dup_checker.should_we_continue_break_or_carry_on(now(),
                                                                       now(),
                                                                       lookup_value=content_hash,
                                                                       lookup_by='sha1')
            if dup_checker.full_crawl:
                self.assertEqual(onwards, 'CONTINUE',
                                 'DupChecker says to %s during a full crawl.' % onwards)
            else:
                self.assertEqual(onwards, 'BREAK',
                                 "DupChecker says to %s but there should be a duplicate in the database. "
                                 "dup_count is %s, and dup_threshold is %s" % (onwards,
                                                                               dup_checker.dup_count,
                                                                               dup_checker.dup_threshold))
            doc.delete()

    def test_should_we_continue_break_or_carry_on_with_dup_found_and_older_date(self):
        content = "this is dummy content that we hash"
        content_hash = hashlib.sha1(content).hexdigest()
        for dup_checker in self.dup_checkers:
            doc = Document(sha1=content_hash, court=self.court)
            doc.save(index=False)
            # Note that the next case occurs prior to the current one
            onwards = dup_checker.should_we_continue_break_or_carry_on(now(), now() - timedelta(days=1),
                                                                       lookup_value=content_hash, lookup_by='sha1')
            if dup_checker.full_crawl:
                self.assertEqual(onwards, 'CONTINUE',
                                 'DupChecker says to %s during a full crawl.' % onwards)
            else:
                self.assertEqual(onwards, 'BREAK',
                                 "DupChecker says to %s but there should be a duplicate in the database. "
                                 "dup_count is %s, and dup_threshold is %s" % (onwards,
                                                                               dup_checker.dup_count,
                                                                               dup_checker.dup_threshold))
            doc.delete()

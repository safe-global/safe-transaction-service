import logging

from django.test import TestCase

from hexbytes import HexBytes

from gnosis.safe.multi_send import MultiSend, MultiSendOperation

from ..indexers.tx_decoder import (CannotDecode, SafeTxDecoder, TxDecoder,
                                   get_safe_tx_decoder, get_tx_decoder)

logger = logging.getLogger(__name__)


class TestTxDecoder(TestCase):
    def test_singleton(self):
        self.assertTrue(isinstance(get_tx_decoder(), TxDecoder))
        self.assertTrue(isinstance(get_safe_tx_decoder(), SafeTxDecoder))

    def test_decode_execute_transaction(self):
        data = HexBytes('0x6a761202000000000000000000000000d9ab7371432d7cc74503290412618c948cddacf200000000000000000'
                        '0000000000000000000000000000000002386f26fc1000000000000000000000000000000000000000000000000'
                        '0000000000000000014000000000000000000000000000000000000000000000000000000000000000000000000'
                        '000000000000000000000000000000000000000000000000000030d400000000000000000000000000000000000'
                        '0000000000000000000000000186a000000000000000000000000000000000000000000000000000000004a817c'
                        '8000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000'
                        '0000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000'
                        '0000000000180000000000000000000000000000000000000000000000000000000000000000000000000000000'
                        '0000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000'
                        '00000000000000000000041512215e7f982c8f8e8429c9008068366dcb96bb3abd9c969f3bf2f97f013da6941e1'
                        '59f13ca524a6b449accf1ce6765ad811ee7b7151f74749e38ac8bc94fb3b1c00000000000000000000000000000'
                        '000000000000000000000000000000000')

        safe_tx_decoder = get_safe_tx_decoder()
        function_name, arguments = safe_tx_decoder.decode_transaction(data)
        self.assertEqual(function_name, 'execTransaction')
        self.assertIn('baseGas', arguments)
        self.assertEqual(type(arguments['data']), str)
        self.assertEqual(type(arguments['baseGas']), int)  # SafeTxDecoder does not change numbers

        safe_tx_decoder = get_tx_decoder()
        function_name, arguments = safe_tx_decoder.decode_transaction(data)
        self.assertEqual(function_name, 'execTransaction')
        self.assertIn('baseGas', arguments)
        self.assertEqual(type(arguments['data']), str)
        self.assertEqual(type(arguments['baseGas']), str)  # TxDecoder casts numbers to strings

    def test_decode_execute_transaction_with_types(self):
        data = HexBytes('0x6a7612020000000000000000000000005592ec0cfb4dbc12d3ab100b257153436a1f0fea0000'
                        '000000000000000000000000000000000000000000000000000000000000000000000000000000'
                        '000000000000000000000000000000000000000000014000000000000000000000000000000000'
                        '000000000000000000000000000000000000000000000000000000000000000000000000000000'
                        '000000000000000000000000000000000000000000000000000000000000000000000000000000'
                        '000000000000000000000000000000000000000000000000000000000000000000000000000000'
                        '000000000000000000000000000000000000000000000000000000000000000000000000000000'
                        '000000000000000000000000000000000000000000000000000000000000000000000000000000'
                        '000000000000000000000001c00000000000000000000000000000000000000000000000000000'
                        '000000000044a9059cbb0000000000000000000000000dc0dfd22c6beab74672eade5f9be5234a'
                        'aa43cc00000000000000000000000000000000000000000000000000005af3107a400000000000'
                        '000000000000000000000000000000000000000000000000000000000000000000000000000000'
                        '00000000000000000000000000000000820000000000000000000000000dc0dfd22c6beab74672'
                        'eade5f9be5234aaa43cc0000000000000000000000000000000000000000000000000000000000'
                        '00000001000000000000000000000000c791cb32ddb43de8260e6a2762b3b03498b615e5000000'
                        '000000000000000000000000000000000000000000000000000000000001000000000000000000'
                        '000000000000000000000000000000000000000000')

        safe_tx_decoder = get_safe_tx_decoder()
        function_name, arguments = safe_tx_decoder.decode_transaction_with_types(data)
        self.assertEqual(function_name, 'execTransaction')
        self.assertEqual(arguments, [{'name': 'to',
                                      'type': 'address',
                                      'value': '0x5592EC0cfb4dbc12D3aB100b257153436a1f0FEa'},
                                     {'name': 'value', 'type': 'uint256', 'value': 0},
                                     {'name': 'data',
                                      'type': 'bytes',
                                      'value': '0xa9059cbb0000000000000000000000000dc0dfd22c6beab74672eade5f9be5234aaa4'
                                               '3cc00000000000000000000000000000000000000000000000000005af3107a4000'},
                                     {'name': 'operation', 'type': 'uint8', 'value': 0},
                                     {'name': 'safeTxGas', 'type': 'uint256', 'value': 0},
                                     {'name': 'baseGas', 'type': 'uint256', 'value': 0},
                                     {'name': 'gasPrice', 'type': 'uint256', 'value': 0},
                                     {'name': 'gasToken',
                                      'type': 'address',
                                      'value': '0x0000000000000000000000000000000000000000'},
                                     {'name': 'refundReceiver',
                                      'type': 'address',
                                      'value': '0x0000000000000000000000000000000000000000'},
                                     {'name': 'signatures',
                                      'type': 'bytes',
                                      'value': '0x0000000000000000000000000dc0dfd22c6beab74672eade5f9be5234aaa43cc00000'
                                               '00000000000000000000000000000000000000000000000000000000000010000000000'
                                               '00000000000000c791cb32ddb43de8260e6a2762b3b03498b615e500000000000000000'
                                               '0000000000000000000000000000000000000000000000001'}]
                         )

    def test_decode_old_execute_transaction(self):
        data = HexBytes('0x6a761202000000000000000000000000a8cc2fc5756f1cba332fefa093ea1d3c6faf559c00000000000000000000'
                        '0000000000000000000000000000002386f26fc1000000000000000000000000000000000000000000000000000000'
                        '0000000000014000000000000000000000000000000000000000000000000000000000000000000000000000000000'
                        '000000000000000000000000000000000000000000030d400000000000000000000000000000000000000000000000'
                        '0000000000000186a000000000000000000000000000000000000000000000000000000004a817c800000000000000'
                        '0000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000'
                        '0000000000000000000000000000000000000000000000000000000000000000000000000000000000018000000000'
                        '0000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000'
                        '0000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000'
                        '000000000000000000000000000000000000000000000000000000000000')

        safe_tx_decoder = get_safe_tx_decoder()
        function_name, arguments = safe_tx_decoder.decode_transaction(data)
        self.assertEqual(function_name, 'execTransaction')
        # self.assertIn('dataGas', arguments)
        self.assertIn('baseGas', arguments)  # Signature of the tx is the same

    def test_decode_multisend(self):
        # Change Safe contract master copy and set fallback manager multisend transaction
        safe_contract_address = '0x5B9ea52Aaa931D4EEf74C8aEaf0Fe759434FeD74'
        value = 0
        operation = MultiSendOperation.CALL.name
        data = HexBytes('0x8d80ff0a0000000000000000000000000000000000000000000000000000000000000020000000000000000000'
                        '00000000000000000000000000000000000000000000f2005b9ea52aaa931d4eef74c8aeaf0fe759434fed740000'
                        '00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000'
                        '000000000000000000000000000000247de7edef00000000000000000000000034cfac646f301356faa8b21e9422'
                        '7e3583fe3f5f005b9ea52aaa931d4eef74c8aeaf0fe759434fed7400000000000000000000000000000000000000'
                        '000000000000000000000000000000000000000000000000000000000000000000000000000000000000000024f0'
                        '8a0323000000000000000000000000d5d82b6addc9027b22dca772aa68d5d74cdbdf440000000000000000000000'
                        '000000')
        change_master_copy_data = HexBytes(
            '0x7de7edef00000000000000000000000034cfac646f301356faa8b21e94227e3583fe3f5f')
        change_fallback_manager_data = HexBytes(
            '0xf08a0323000000000000000000000000d5d82b6addc9027b22dca772aa68d5d74cd'
            'bdf44')
        tx_decoder = get_tx_decoder()
        expected = [
            {'operation': operation,
             'to': safe_contract_address,
             'value': value,
             'data': change_master_copy_data.hex(),
             'decoded_data': {
                 'method': 'changeMasterCopy',
                 'parameters': [
                     {'name': '_masterCopy',
                      'type': 'address',
                      'value': '0x34CfAC646f301356fAa8B21e94227e3583Fe3F5F'
                      }
                 ]
             }
             },
            {'operation': operation,
             'to': safe_contract_address,
             'value': value,
             'data': change_fallback_manager_data.hex(),
             'decoded_data': {
                 'method': 'setFallbackHandler',
                 'parameters': [
                     {'name': 'handler',
                      'type': 'address',
                      'value': '0xd5D82B6aDDc9027B22dCA772Aa68D5d74cdBdF44'
                      }
                 ]
             }
             }
        ]
        # Get just the multisend object
        self.assertEqual(tx_decoder.decode_multisend_with_types(data), expected)

        # Now decode all the data
        expected = ('multiSend',
                    [{'name': 'transactions',
                      'type': 'bytes',
                      'value': '0x005b9ea52aaa931d4eef74c8aeaf0fe759434fed74000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000247de7edef00000000000000000000000034cfac646f301356faa8b21e94227e3583fe3f5f005b9ea52aaa931d4eef74c8aeaf0fe759434fed7400000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000024f08a0323000000000000000000000000d5d82b6addc9027b22dca772aa68d5d74cdbdf44',
                      'decoded_value': [
                          {'operation': operation,
                           'to': safe_contract_address,
                           'value': value,
                           'data': change_master_copy_data.hex(),
                           'decoded_data': {
                               'method': 'changeMasterCopy',
                               'parameters': [
                                   {'name': '_masterCopy',
                                    'type': 'address',
                                    'value': '0x34CfAC646f301356fAa8B21e94227e3583Fe3F5F'
                                    }
                               ]
                           }
                           },
                          {'operation': operation,
                           'to': safe_contract_address,
                           'value': value,
                           'data': change_fallback_manager_data.hex(),
                           'decoded_data': {
                               'method': 'setFallbackHandler',
                               'parameters': [
                                   {'name': 'handler',
                                    'type': 'address',
                                    'value': '0xd5D82B6aDDc9027B22dCA772Aa68D5d74cdBdF44'
                                    }
                               ]
                           }
                           }
                      ]
                      }])
        self.assertEqual(tx_decoder.decode_transaction_with_types(data), expected)

        # Safe tx decoder cannot decode it. It would be problematic for the internal tx indexer
        safe_tx_decoder = get_safe_tx_decoder()
        with self.assertRaises(CannotDecode):
            safe_tx_decoder.decode_transaction_with_types(data)

    def test_decode_multisend_not_valid(self):
        # Same data with some stuff deleted
        data = HexBytes('0x8d80ff0a0000000000000000000000000000000000000000000000000000000000000020000000000000000000'
                        '00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000'
                        '000000000000000000000000000000247de7edef00000000000000000000000034cfac646f301356faa8b21e9422'
                        '7e3583fe3f5f005b9ea52aaa931d4eef74c8aeaf0fe759434fed7400000000000000000000000000000000000000'
                        '000000000000000000000000000000000000000000000000000000000000000000000000000000000000000024f0'
                        '8a0323000000000000000000000000d5d82b6addc9027b22dca772aa68d5d74cdbdf440000000000000000000000'
                        '000000')
        tx_decoder = get_tx_decoder()
        self.assertEqual(tx_decoder.decode_multisend_with_types(data), [])
        self.assertEqual(tx_decoder.decode_transaction_with_types(data),
                         ('multiSend', [{'name': 'transactions', 'type': 'bytes', 'value': '0x', 'decoded_value': []}]))

    def test_supported_fn_selectors(self):
        for tx_decoder in (TxDecoder(), get_tx_decoder(), get_safe_tx_decoder()):
            self.assertIn(b'jv\x12\x02', tx_decoder.supported_fn_selectors)  # execTransaction for Safe >= V1.0.0
            self.assertIn(b'\xb6>\x80\r', tx_decoder.supported_fn_selectors)  # setup for Safe V1.1.0
            self.assertIn(b'\xa9z\xb1\x8a', tx_decoder.supported_fn_selectors)  # setup for Safe V1.0.0

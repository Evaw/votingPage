$(document).ready(
	function(){
		"use strict";
		var togglePicSubmission = function(){
			if($('.picture-submission-container').hasClass('no-height')){
				$('.picture-submission-container').removeClass('no-height');
			} else {
				$('.picture-submission-container').addClass('no-height')
			}
			
		};
		$('#pic-submission-toggle-btn').bind('click',	togglePicSubmission);
		
	}
);
